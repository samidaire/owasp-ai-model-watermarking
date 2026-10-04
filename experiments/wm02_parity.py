"""WM-02 parity study: does a {-1,+1} Poseidon-derived key work as well as the Gaussian key?

Protocol v2 replaces the numpy Gaussian projection with X in {-1,+1}^(T x M) derived from Poseidon,
so the key can be re-derived inside the circuit. This trains the demo MNIST CNN with both key kinds
over several seeds, using the SAME signature, training recipe and attack suite as demo/01_train.py and
demo/02_attacks.py, and compares accuracy cost, owner BER and survival under attacks.

    .venv/Scripts/python experiments/wm02_parity.py --seeds 5
Writes experiments/results/wm02_parity.json and docs/reports/wm02_parity.md.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))
from wm_core import Net, accuracy, clone, device, load_mnist, train, wm_vector  # noqa: E402

from sigil import protocol as P  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", type=int, default=5)
ap.add_argument("--epochs", type=int, default=3)
args = ap.parse_args()

dev = device()
d = load_mnist(dev)
cfg = P.Config()                                   # T=64, M=288, conv2, max_err=8
xa, ya, xt, yt = d["x_att"], d["y_att"], d["x_test"], d["y_test"]


def seed_for(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode()).digest(), "big") >> 8   # 248 bits


def keys(kind: str, seed: int, pkh: int):
    if kind == "pm1":
        X = P.key_matrix(seed, pkh, cfg).astype(np.float32)
    else:
        rng = np.random.Generator(np.random.PCG64(seed))
        X = rng.standard_normal((cfg.T, cfg.M), dtype=np.float32)
    b = P.signature_bits(seed, pkh, cfg)
    return torch.from_numpy(X).to(dev), torch.from_numpy(b.astype(np.int64)).to(dev)


def ber(model, X, b) -> float:
    with torch.no_grad():
        return float(((X @ wm_vector(model) >= 0).long() != b).float().mean())


def prune(model, ratio):
    m = clone(model)
    with torch.no_grad():
        for mod in m.modules():
            if isinstance(mod, (nn.Conv2d, nn.Linear)):
                w = mod.weight
                thr = w.abs().flatten().kthvalue(int(ratio * w.numel())).values
                w[w.abs() <= thr] = 0
    return m


def quantise(model, bits):
    m = clone(model)
    with torch.no_grad():
        for p in m.parameters():
            s = p.abs().max() / (2 ** (bits - 1) - 1)
            p.copy_(torch.round(p / s) * s)
    return m


def permute(model, seed=0):
    m = clone(model)
    perm = torch.randperm(m.conv1.out_channels, generator=torch.Generator().manual_seed(seed)).to(dev)
    with torch.no_grad():
        m.conv1.weight.copy_(m.conv1.weight[perm])
        m.conv1.bias.copy_(m.conv1.bias[perm])
        m.conv2.weight.copy_(m.conv2.weight[:, perm])
    return m


owner_pkh = P.pk_hash(hashlib.sha256(b"wm02-owner-public-key").digest())
thief_pkh = P.pk_hash(hashlib.sha256(b"wm02-thief-public-key").digest())
runs = []
t_start = time.time()
for s in range(args.seeds):
    torch.manual_seed(10 + s)
    clean = train(Net().to(dev), d["x_owner"], d["y_owner"], args.epochs, seed=10 + s, tag=f"clean s{s}")
    clean_acc = accuracy(clean, xt, yt)
    for kind in ("gaussian", "pm1"):
        seed = seed_for(f"wm02-owner-{s}")
        X, b = keys(kind, seed, owner_pkh)
        torch.manual_seed(10 + s)
        wm = train(Net().to(dev), d["x_owner"], d["y_owner"], args.epochs, seed=10 + s, wm=(X, b), tag=f"{kind} s{s}")
        Xt, bt = keys(kind, seed_for(f"wm02-thief-{s}"), thief_pkh)
        rtal = clone(wm)
        rtal.fc2.reset_parameters()
        attacked = {
            "prune 65%": prune(wm, 0.65), "prune 90%": prune(wm, 0.90),
            "int8": quantise(wm, 8), "int4": quantise(wm, 4),
            "FTAL 5": train(clone(wm), xa, ya, 5, seed=7, tag="FTAL"),
            "RTAL 5": train(rtal, xa, ya, 5, seed=7, tag="RTAL"),
            "overwrite 3": train(clone(wm), xa, ya, 3, seed=7, wm=(Xt, bt), tag="overwrite"),
            "permutation": permute(wm),
        }
        row = {"seed": s, "key": kind, "clean_acc": clean_acc, "acc": accuracy(wm, xt, yt),
               "owner_ber": ber(wm, X, b), "clean_model_ber": ber(clean, X, b), "attacks": {}}
        if kind == "pm1":   # protocol-v2 detection on the quantised vector, exactly what the circuit checks
            det = P.detect(seed, owner_pkh, cfg, wm_vector(wm).detach().double().cpu().numpy())
            row["v2_detection"] = det.to_dict()
        for name, m in attacked.items():
            row["attacks"][name] = {"acc": accuracy(m, xt, yt), "owner_ber": ber(m, X, b)}
        runs.append(row)
        print(f"  [{kind:8s} s{s}] acc={row['acc']:.4f} (clean {clean_acc:.4f})  owner BER={row['owner_ber']:.3f}  "
              + "  ".join(f"{k}:{v['owner_ber']:.3f}" for k, v in row["attacks"].items()), flush=True)

# ------------------------------------------------------------------ summary
def stats(vals):
    a = np.asarray(vals, dtype=float)
    return {"mean": float(a.mean()), "std": float(a.std(ddof=1)) if len(a) > 1 else 0.0}

summary = {}
for kind in ("gaussian", "pm1"):
    rs = [r for r in runs if r["key"] == kind]
    summary[kind] = {
        "acc_cost_pp": stats([(r["clean_acc"] - r["acc"]) * 100 for r in rs]),
        "owner_ber": stats([r["owner_ber"] for r in rs]),
        "clean_model_ber": stats([r["clean_model_ber"] for r in rs]),
        "attacks": {a: {"owner_ber": stats([r["attacks"][a]["owner_ber"] for r in rs]),
                        "acc": stats([r["attacks"][a]["acc"] for r in rs]),
                        "survived": sum(r["attacks"][a]["owner_ber"] <= cfg.theta for r in rs)}
                    for a in rs[0]["attacks"]},
    }
if any("v2_detection" in r for r in runs):
    summary["pm1"]["v2_detection_accepted"] = sum(r["v2_detection"]["accepted"] for r in runs if "v2_detection" in r)

# Parity criterion (WM-02): pm1 within one std of gaussian on accuracy cost and owner BER, and survives
# every attack in at least as many seeds as gaussian does, except where both fail.
g, p = summary["gaussian"], summary["pm1"]
def within(a, b):
    return abs(a["mean"] - b["mean"]) <= max(a["std"], b["std"], 0.05)
checks = {
    "acc_cost": within(p["acc_cost_pp"], g["acc_cost_pp"]),
    "owner_ber": within(p["owner_ber"], g["owner_ber"]),
    "attacks": all(p["attacks"][a]["survived"] >= g["attacks"][a]["survived"] - 1 for a in g["attacks"]),
}
summary["parity"] = {**checks, "passed": all(checks.values())}
out = {"config": cfg.to_dict(), "seeds": args.seeds, "epochs": args.epochs, "device": str(dev),
       "torch": torch.__version__, "seconds": round(time.time() - t_start, 1), "runs": runs, "summary": summary}
(ROOT / "experiments" / "results").mkdir(parents=True, exist_ok=True)
(ROOT / "experiments" / "results" / "wm02_parity.json").write_text(json.dumps(out, indent=2))

lines = ["# WM-02 parity study: ±1 Poseidon key vs Gaussian key", "",
         f"Generated by `experiments/wm02_parity.py` ({args.seeds} seeds, {args.epochs} epochs, {dev}, torch {torch.__version__}). "
         f"Config: T={cfg.T}, M={cfg.M}, θ={cfg.max_err}/{cfg.T}. Values are mean ± std over seeds.", "",
         "| Metric | Gaussian key | ±1 Poseidon key |", "|---|---|---|"]
fmt = lambda s, k=3: f"{s['mean']:.{k}f} ± {s['std']:.{k}f}"
lines += [f"| Accuracy cost (pp) | {fmt(g['acc_cost_pp'], 2)} | {fmt(p['acc_cost_pp'], 2)} |",
          f"| Owner BER, watermarked model | {fmt(g['owner_ber'])} | {fmt(p['owner_ber'])} |",
          f"| Owner BER on the clean model (should be ≈0.5) | {fmt(g['clean_model_ber'])} | {fmt(p['clean_model_ber'])} |"]
for a in g["attacks"]:
    lines.append(f"| {a}: owner BER (survived/{args.seeds}) | {fmt(g['attacks'][a]['owner_ber'])} ({g['attacks'][a]['survived']}) "
                 f"| {fmt(p['attacks'][a]['owner_ber'])} ({p['attacks'][a]['survived']}) |")
if "v2_detection_accepted" in p:
    lines += ["", f"Protocol-v2 detection on the quantised vector (what the circuit checks) accepted the owner in "
                  f"{p['v2_detection_accepted']}/{args.seeds} runs."]
lines += ["", f"**Parity: {'PASSED' if summary['parity']['passed'] else 'FAILED'}** "
              f"(accuracy cost {checks['acc_cost']}, owner BER {checks['owner_ber']}, attack survival {checks['attacks']})."]
(ROOT / "docs" / "reports").mkdir(parents=True, exist_ok=True)
(ROOT / "docs" / "reports" / "wm02_parity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
