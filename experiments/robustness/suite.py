"""The attack matrix: which sigil.attacks calls make up one row each, driven by a YAML config.

``plan(cfg_attacks, ctx)`` returns a list of rows ``{"name", "family", "params", "run"}`` where ``run()``
returns ``(attacked_model, info)``. ``evaluate`` scores a model for the owner (white-box errors on the
quantised Uchida vector, exactly what the circuit checks) and on the trigger set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import torch

from sigil import attacks as A
from sigil import triggerset as TS


def recipe(d: dict, seed: int) -> A.Fit:
    keys = {"epochs", "lr", "batch_size", "optimizer", "momentum", "weight_decay", "schedule", "amp", "label_smoothing"}
    return A.Fit(**{k: v for k, v in d.items() if k in keys}, seed=seed)


@dataclass
class Context:
    layer: str                       # watermarked layer
    producer: str                    # layer whose output channels feed `layer` (for permutation)
    fineprune_layer: str
    x_att: torch.Tensor
    y_att: torch.Tensor
    x_calib: torch.Tensor
    thief_X: np.ndarray
    thief_b: np.ndarray
    student: Callable[[int], torch.nn.Module]       # fresh, untrained model of the victim's architecture
    seed: int = 0
    augment: Callable | None = None                  # attacker's training augmentation
    query_augment: Callable | None = None            # distinct views when the query budget exceeds the pool
    extra: dict = field(default_factory=dict)


def plan(c: dict, ctx: Context) -> list[dict]:
    s = ctx.seed
    xa, ya, aug = ctx.x_att, ctx.y_att, ctx.augment
    rows = []

    def add(name, family, params, run):
        rows.append({"name": name, "family": family, "params": params, "run": run})

    add("none (stolen as-is)", "baseline", {}, lambda m: (A.clone(m), {}))
    for r in c.get("prune_ratios", []):
        add(f"prune {round(r * 100)}%", "prune", {"ratio": r}, lambda m, r=r: (A.prune_magnitude(m, r), {}))
    rec = c.get("recovery")
    for r in c.get("recovery_ratios", []):
        add(f"prune {round(r * 100)}% + recovery", "prune+recovery", {"ratio": r, **rec},
            lambda m, r=r: (A.prune_finetune(m, r, xa, ya, recipe(rec, s), augment=aug), {}))
    for r in c.get("channel_ratios", []):
        add(f"channel prune {round(r * 100)}%", "channel prune", {"ratio": r}, lambda m, r=r: (A.prune_channels(m, r), {}))
    for r in c.get("channel_recovery_ratios", []):
        add(f"channel prune {round(r * 100)}% + recovery", "channel prune", {"ratio": r, **rec},
            lambda m, r=r: (A.prune_finetune(m, r, xa, ya, recipe(rec, s), structured=True, augment=aug), {}))
    fp = c.get("fineprune")
    for r in (fp or {}).get("ratios", []):
        add(f"fine-pruning {round(r * 100)}% ({ctx.fineprune_layer})", "fine-pruning", {"ratio": r, **fp["fit"]},
            lambda m, r=r: (A.fine_prune(m, ctx.fineprune_layer, r, xa, ya, recipe(fp["fit"], s), augment=aug), {}))
    for q in c.get("quantisation", []):
        act = q.get("act_bits")
        tag = f"int{q['bits']} per-{q['granularity']}" + (f" (W{q['bits']}A{act})" if act else f" (W{q['bits']}, weights only)")
        add(tag, "quantisation", q, lambda m, q=q, act=act: (
            A.ptq(m, q["bits"], ctx.x_calib if act else None, granularity=q["granularity"], act_bits=act), {}))
    ft = c.get("finetune")
    if ft:
        e = ft["epochs"]
        add(f"FTLL {e} ep", "fine-tune", ft, lambda m: (A.ftll(m, xa, ya, recipe(ft, s), augment=aug), {}))
        add(f"FTAL {e} ep", "fine-tune", ft, lambda m: (A.ftal(m, xa, ya, recipe(ft, s), augment=aug), {}))
        rt = c.get("retrain", ft)
        add(f"RTLL {rt['epochs']} ep", "fine-tune", rt, lambda m: (A.rtll(m, xa, ya, recipe(rt, s), augment=aug), {}))
        add(f"RTAL {rt['epochs']} ep", "fine-tune", rt, lambda m: (A.rtal(m, xa, ya, recipe(rt, s), augment=aug), {}))
    ow = c.get("overwrite")
    if ow:
        add(f"overwrite (thief v2 key, λ={ow['lam']}, {ow['fit']['epochs']} ep)", "overwrite", {"lam": ow["lam"], **ow["fit"]},
            lambda m: (A.overwrite(m, xa, ya, recipe(ow["fit"], s), layer=ctx.layer, X=ctx.thief_X, b=ctx.thief_b,
                                   lam=ow["lam"], augment=aug), {}))
    if c.get("permutation"):
        pft = c["permutation"].get("finetune", ft)

        def perm(m):
            return A.permute_channels(m, ctx.producer, ctx.layer, seed=1000 + s)

        def perm_realign(m):
            p = perm(m)
            r, pi, info = A.realign(p, m, ctx.producer, ctx.layer)
            return r, {"suspect": p, "realign_perm": pi, **info}

        def perm_ft(m):
            return A.ftal(perm(m), xa, ya, recipe(pft, s), augment=aug)

        def perm_ft_realign(m):
            p = perm_ft(m)
            r, pi, info = A.realign(p, m, ctx.producer, ctx.layer)
            return r, {"suspect": p, "realign_perm": pi, **info}

        add("permutation", "permutation", {"producer": ctx.producer}, lambda m: (perm(m), {}))
        add("permutation + owner realign", "permutation", {"producer": ctx.producer}, perm_realign)
        add(f"permutation + FTAL {pft['epochs']} ep", "permutation", pft, lambda m: (perm_ft(m), {}))
        add(f"permutation + FTAL {pft['epochs']} ep + owner realign", "permutation", pft, perm_ft_realign)
    for k in c.get("kmeans", []):
        add(f"k-means sharing k={k}", "compression", {"clusters": k},
            lambda m, k=k: (A.kmeans_share(m, k, seed=s), {}))
    for f in c.get("svd_linear", []):
        add(f"SVD linear rank {round(f * 100)}%", "compression", {"rank_fraction": f, "include_conv": False},
            lambda m, f=f: (A.low_rank(m, f), {}))
    for f in c.get("svd_all", []):
        add(f"SVD conv+linear rank {round(f * 100)}%", "compression", {"rank_fraction": f, "include_conv": True},
            lambda m, f=f: (A.low_rank(m, f, include_conv=True), {}))
    ds = c.get("distill")
    if ds:
        add(f"distillation (white-box student, τ={ds['temperature']}, {ds['fit']['epochs']} ep)", "distillation",
            {"temperature": ds["temperature"], **ds["fit"]},
            lambda m: (A.distill(m, ctx.student(5000 + s), xa, recipe(ds["fit"], s), temperature=ds["temperature"],
                                 augment=aug), {}))
    for ex in c.get("extraction", []):
        def run(m, ex=ex):
            st, info = A.extract(m, ctx.student(6000 + s), xa, ex["budget"], recipe(ex["fit"], s), output=ex["output"],
                                 query_augment=ctx.query_augment, train_augment=aug)
            return st, info
        add(f"extraction {ex['budget'] // 1000}k queries ({ex['output']})", "extraction",
            {"budget": ex["budget"], "output": ex["output"], **ex["fit"]}, run)
    return rows


def evaluate(model, owner, layer: str, x_test, y_test, ts: TS.TriggerSet | None, mean, std, ts_threshold: int | None,
             bs: int = 1000):
    """Accuracy, the owner's v2 detection (errors on the quantised Uchida vector) and trigger-set score."""
    w = A.uchida_vector(A.get_module(model, layer).weight).detach().double().cpu().numpy()
    det = owner.detect(w)
    out = {"acc": A.accuracy(model, x_test, y_test, bs), "errors": det.errors, "ber": det.ber,
           "survived": det.accepted}
    if ts is not None:
        r = TS.verify(TS.torch_predictor(model), ts, mean, std, k=ts_threshold)
        out.update({"trigger_matches": r.matches, "trigger_acc": r.accuracy, "trigger_accepted": r.accepted})
    return out
