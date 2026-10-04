"""DEMO B: the thief tries to strip the watermark (OWASP AI Exchange requirement R1).

Attack subset taken from Lukas et al., SoK (IEEE S&P 2022), Table III:
  weight pruning, weight quantisation, fine-tuning (FTAL), re-training the last layer (RTAL),
  overwriting with the thief's own watermark, and feature permutation (the SoK's own attack).
The thief owns 10k in-domain samples (train[50000:]) the owner never used.
"""
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn

from wm_core import (RESULTS, THIEF_ID, THETA, accuracy, banner, ber, clone, derive_key,
                     derive_signature, device, extract_bits, load_mnist, load_model,
                     load_owner, train)

dev = device()
d = load_mnist(dev)
_, _, _, X, b = load_owner(dev)
stolen = load_model("watermarked", dev)
xa, ya, xt, yt = d["x_att"], d["y_att"], d["x_test"], d["y_test"]


def prune(model, ratio):
    """Per-layer magnitude pruning of every conv/linear weight tensor."""
    m = clone(model)
    with torch.no_grad():
        for mod in m.modules():
            if isinstance(mod, (nn.Conv2d, nn.Linear)) and ratio > 0:
                w = mod.weight
                k = int(ratio * w.numel())
                thr = w.abs().flatten().kthvalue(k).values
                w[w.abs() <= thr] = 0
    return m


def quantise(model, bits=8):
    m = clone(model)
    with torch.no_grad():
        for p in m.parameters():
            s = p.abs().max() / (2 ** (bits - 1) - 1)
            p.copy_(torch.round(p / s) * s)
    return m


def permute_features(model, seed=0):
    """Functionally identical model: shuffle conv1 output channels and conv2 input channels."""
    m = clone(model)
    perm = torch.randperm(m.conv1.out_channels, generator=torch.Generator().manual_seed(seed)).to(dev)
    with torch.no_grad():
        m.conv1.weight.copy_(m.conv1.weight[perm])
        m.conv1.bias.copy_(m.conv1.bias[perm])
        m.conv2.weight.copy_(m.conv2.weight[:, perm])
    return m


rows = []


def record(name, family, model):
    acc, e = accuracy(model, xt, yt), ber(extract_bits(model, X), b)
    verdict = "WATERMARK SURVIVES" if e <= THETA else "watermark REMOVED"
    print(f"  {name:<28} acc={acc:.4f}   owner BER={e:.3f}   -> {verdict}")
    rows.append({"attack": name, "family": family, "accuracy": acc, "owner_ber": e})


banner("DEMO B: Removal attacks on the stolen model  (acceptance threshold BER <= %.3f)" % THETA)
record("none (stolen as-is)", "baseline", stolen)

print("\n  -- weight pruning (per-layer magnitude) --")
for r in [0.2, 0.4, 0.65, 0.8, 0.9, 0.95]:
    record(f"prune {int(r * 100)}%", "prune", prune(stolen, r))

print("\n  -- quantisation --")
record("int8 quantisation", "quantise", quantise(stolen, 8))
record("int4 quantisation", "quantise", quantise(stolen, 4))

print("\n  -- fine-tuning on the thief's own 10k samples --")
record("FTAL 1 epoch", "finetune", train(clone(stolen), xa, ya, 1, seed=7, tag="FTAL-1"))
record("FTAL 5 epochs", "finetune", train(clone(stolen), xa, ya, 5, seed=7, tag="FTAL-5"))
rtal = clone(stolen)
rtal.fc2.reset_parameters()
record("RTAL 5 epochs", "finetune", train(rtal, xa, ya, 5, seed=7, tag="RTAL-5"))

print("\n  -- overwriting: thief embeds their own Uchida watermark in the same layer --")
ts = b"thief-overwrite-seed"
Xt = torch.from_numpy(derive_key(ts)).to(dev)
bt = torch.from_numpy(derive_signature(ts, THIEF_ID)).to(dev)
record("overwrite 3 epochs", "overwrite", train(clone(stolen), xa, ya, 3, seed=7, wm=(Xt, bt), tag="overwrite"))

def realign(suspect, reference):
    """Owner-side countermeasure: the owner still holds the original model, so match each
    original conv1 filter to its most similar suspect filter and undo the permutation."""
    A = torch.nn.functional.normalize(reference.conv1.weight.flatten(1), dim=1)
    B = torch.nn.functional.normalize(suspect.conv1.weight.flatten(1), dim=1)
    perm = (A @ B.T).argmax(1)
    m = clone(suspect)
    with torch.no_grad():
        m.conv1.weight.copy_(suspect.conv1.weight[perm])
        m.conv1.bias.copy_(suspect.conv1.bias[perm])
        m.conv2.weight.copy_(suspect.conv2.weight[:, perm])
    return m


print("\n  -- feature permutation (SoK, 'Feature Permutation (Ours)') --")
permuted = permute_features(stolen)
record("feature permutation", "permute", permuted)
record("permutation + owner realign", "permute", realign(permuted, stolen))

RESULTS.mkdir(exist_ok=True)
with open(RESULTS / "attacks.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)

# ---- figure for the slides
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6))
pr = [r for r in rows if r["family"] in ("baseline", "prune")]
x = [0] + [int(r["attack"].split()[1][:-1]) for r in pr[1:]]
a1.plot(x, [r["accuracy"] for r in pr], "o-", label="test accuracy")
a1.plot(x, [r["owner_ber"] for r in pr], "s-", label="owner BER")
a1.axhline(THETA, ls="--", c="grey", lw=1, label=f"BER threshold {THETA:.3f}")
a1.set_xlabel("weights pruned per layer (%)")
a1.set_ylim(-0.02, 1.02)
a1.set_title("Pruning: accuracy vs watermark")
a1.legend(loc="center left")
other = [r for r in rows if r["family"] not in ("prune",)]
names = [r["attack"] for r in other]
idx = np.arange(len(other))
a2.bar(idx - 0.2, [r["accuracy"] for r in other], 0.4, label="test accuracy")
a2.bar(idx + 0.2, [r["owner_ber"] for r in other], 0.4, label="owner BER")
a2.axhline(THETA, ls="--", c="grey", lw=1)
a2.set_xticks(idx, names, rotation=30, ha="right")
a2.set_ylim(0, 1.3)
a2.set_title("Other attacks")
a2.legend(loc="upper center", ncol=2)
fig.suptitle("Uchida watermark under SoK-style removal attacks (MNIST CNN)")
fig.tight_layout()
fig.savefig(RESULTS / "attacks.png", dpi=150)
print(f"\n  Saved results/attacks.csv and results/attacks.png")

# ---- structured results for the web UI (additive)
from demo_common import current_commitment, write_json
write_json("attacks.json", {"commitment": current_commitment(), "threshold": THETA,
                            "rows": [{**r, "survives": r["owner_ber"] <= THETA} for r in rows]})
