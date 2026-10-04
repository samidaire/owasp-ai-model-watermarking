"""MNIST attack matrix (ROB-01..ROB-04, WM-06, FIX-16): protocol-v2 mark (T=64, conv2) under every attack.

For each seed: a clean model (accuracy reference), a white-box-marked model ("wm") and a dual-mark model
("dual": white-box + committed trigger set). Every attack in mnist.yaml runs on wm and dual; each row
records accuracy, the attacker's accuracy cost, the owner's v2 detection on the quantised Uchida vector
(errors, BER, survived = errors <= max_err) and the trigger-set score.

    python experiments/robustness/mnist_matrix.py [--seeds 0 1] [--config experiments/robustness/mnist.yaml]
Writes results/mnist_matrix.json and .csv; saves the attacked wm models of zk_seed for mnist_zk.py.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import torch

from common import CKPT, HERE, RESULT_SCHEMA, RESULTS, GpuClock, Owner, cached, device, env_info, load_config, log, stats, write_csv, write_json
from sigil import attacks as A
from sigil import protocol as P
from sigil import triggerset as TS
from suite import Context, evaluate, plan, recipe
from wm_core import Net, load_mnist

MEAN, STD = [0.1307], [0.3081]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "mnist.yaml"))
    ap.add_argument("--seeds", type=int, nargs="*")
    ap.add_argument("--out", default="mnist_matrix")
    args = ap.parse_args()
    cfg = load_config(args.config)
    seeds = args.seeds if args.seeds is not None else cfg["seeds"]
    dev = device()
    A.deterministic(True)
    env = env_info(dev)
    d = load_mnist(dev)
    wmc = cfg["watermark"]
    pcfg = P.Config(T=wmc["T"], M=wmc["M"], layer=wmc["layer"], scale_bits=wmc["scale_bits"], w_bits=wmc["w_bits"],
                    max_err=wmc["max_err"])
    tsc = cfg["triggerset"]
    spec = TS.Spec(n=tsc["n"], shape=(1, 28, 28), num_classes=10, grid=tsc["grid"])
    k_ts = TS.threshold(spec.n, spec.num_classes, tsc["fpr"])
    clock = GpuClock()
    rows, bases, public = [], [], {}
    t_start = time.time()
    for s in seeds:
        owner = Owner(f"m5/mnist/owner/{s}", pcfg)
        thief = Owner(f"m5/mnist/thief/{s}", pcfg)
        ts = TS.derive(owner.seed, owner.pkh, spec)
        public[s] = {"pk_hash": str(owner.pkh), "config_hash": str(P.config_hash(pcfg)),
                     "commitment": str(P.commitment(owner.seed, owner.pkh, pcfg)), "trigger_commitment": ts.commitment()}

        def build(kind, s=s, owner=owner, ts=ts):
            def go():
                torch.manual_seed(1000 + s)
                m = Net().to(dev)
                reg = A.uchida_regularizer(wmc["layer"], owner.X, owner.b, wmc["lam"]) if kind != "clean" else None
                extra = TS.sampler(ts, MEAN, STD, tsc["per_batch"], dev) if kind == "dual" else None
                log(f"train mnist {kind} s{s}")
                return A.fit(m, d["x_owner"], d["y_owner"], recipe(cfg["owner_training"], 1000 + s),
                             regularizer=reg, extra=extra)
            with clock:
                return cached(CKPT / f"mnist_{kind}_s{s}.pt", Net, go, dev)[0]

        models = {k: build(k) for k in ("clean", "wm", "dual")}
        for kind, m in models.items():
            with clock:
                ev = evaluate(m, owner, wmc["layer"], d["x_test"], d["y_test"], ts, MEAN, STD, k_ts)
            bases.append({"seed": s, "model": kind, **ev})
            log(f"s{s} {kind}: {ev}")
        clean_acc = next(b["acc"] for b in bases if b["seed"] == s and b["model"] == "clean")
        ctx = Context(layer=wmc["layer"], producer=wmc["producer"], fineprune_layer=wmc["layer"],
                      x_att=d["x_att"], y_att=d["y_att"], x_calib=d["x_att"][:2000],
                      thief_X=thief.X, thief_b=thief.b, student=lambda sd: _fresh(sd, dev), seed=100 + s)
        for kind in cfg["models"]:
            stolen = models[kind]
            base_acc = next(b["acc"] for b in bases if b["seed"] == s and b["model"] == kind)
            zk_dir = CKPT / f"mnist_attacked_s{s}" if (s == cfg.get("zk_seed") and kind == "wm") else None
            manifest = []
            for row in plan(cfg["attacks"], ctx):
                t0 = time.time()
                with clock:
                    attacked, info = row["run"](stolen)
                    ev = evaluate(attacked, owner, wmc["layer"], d["x_test"], d["y_test"], ts, MEAN, STD, k_ts)
                suspect = info.pop("suspect", None)
                rec = {"seed": s, "model": kind, "attack": row["name"], "family": row["family"],
                       "params": json.dumps(row["params"], sort_keys=True), **ev,
                       "acc_drop_pp": round((base_acc - ev["acc"]) * 100, 4),
                       "acc_vs_clean_pp": round((clean_acc - ev["acc"]) * 100, 4),
                       "info": json.dumps({k: v for k, v in info.items() if k != "realign_perm"}, sort_keys=True),
                       "seconds": round(time.time() - t0, 2)}
                rows.append(rec)
                log(f"s{s} {kind:4s} {row['name']:<52s} acc={ev['acc']:.4f} err={ev['errors']:2d} "
                    f"surv={ev['survived']!s:5s} trig={ev.get('trigger_acc', 0):.2f}")
                if zk_dir is not None:
                    zk_dir.mkdir(parents=True, exist_ok=True)
                    f = zk_dir / f"{slug(row['name'])}.pt"
                    # the suspect FILE is what the thief deploys; for realigned rows the owner discloses the perm
                    torch.save((suspect if suspect is not None else attacked).state_dict(), f)
                    manifest.append({"attack": row["name"], "family": row["family"], "file": f.name,
                                     "realign_perm": info.get("realign_perm"), "errors": ev["errors"],
                                     "survived": ev["survived"]})
            if zk_dir is not None:
                (zk_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))

    # ------------------------------------------------------------------ summary over seeds
    summary = {}
    for kind in cfg["models"]:
        for name in dict.fromkeys(r["attack"] for r in rows if r["model"] == kind):
            rs = [r for r in rows if r["model"] == kind and r["attack"] == name]
            summary.setdefault(kind, {})[name] = {
                "family": rs[0]["family"], "n": len(rs),
                "acc": stats([r["acc"] for r in rs]), "acc_drop_pp": stats([r["acc_drop_pp"] for r in rs]),
                "errors": stats([r["errors"] for r in rs]), "ber": stats([r["ber"] for r in rs]),
                "survived": sum(r["survived"] for r in rs),
                "trigger_acc": stats([r.get("trigger_acc") for r in rs]),
                "trigger_accepted": sum(bool(r.get("trigger_accepted")) for r in rs),
            }
    base_summary = {k: {"acc": stats([b["acc"] for b in bases if b["model"] == k]),
                        "errors": stats([b["errors"] for b in bases if b["model"] == k]),
                        "trigger_acc": stats([b["trigger_acc"] for b in bases if b["model"] == k])}
                    for k in ("clean", "wm", "dual")}
    for k in ("wm", "dual"):
        base_summary[k]["acc_cost_pp"] = stats([
            (next(b["acc"] for b in bases if b["seed"] == s and b["model"] == "clean")
             - next(b["acc"] for b in bases if b["seed"] == s and b["model"] == k)) * 100 for s in seeds])
    out = {"schema": RESULT_SCHEMA, "experiment": "mnist_matrix", "config": cfg, "protocol_config": pcfg.to_dict(),
           "trigger_threshold": k_ts, "trigger_spec": {"n": spec.n, "shape": list(spec.shape), "grid": spec.grid},
           "seeds": seeds, "env": env, "public_records": public, "base_models": bases, "base_summary": base_summary,
           "rows": rows, "summary": summary, "gpu_seconds": round(clock.seconds, 1),
           "wall_seconds": round(time.time() - t_start, 1)}
    write_json(RESULTS / f"{args.out}.json", out)
    write_csv(RESULTS / f"{args.out}.csv", rows)
    log(f"done: {len(rows)} rows, GPU {clock.seconds:.0f}s -> results/{args.out}.json")


def _fresh(seed: int, dev) -> torch.nn.Module:
    torch.manual_seed(seed)
    return Net().to(dev)


if __name__ == "__main__":
    main()
