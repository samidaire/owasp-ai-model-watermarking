"""WM-07: null-model calibration of theta on MNIST.

Trains independent never-watermarked models and measures how many signature bits they get wrong against
the owners' keys (protocol v2 detection on the quantised Uchida vector). The false-positive rate at
max_err = T/8 is reported with a Clopper-Pearson 95% upper bound next to the binomial reference
P[Bin(T, 1/2) <= max_err]. Also: a pooled study over many independent keys, the same nulls after
owner-side realignment (does ROB-06 realignment create false positives?), and the trigger-set FPR.

    python experiments/robustness/mnist_nulls.py
Writes results/mnist_nulls.json (needs the mnist_matrix wm checkpoints for the realignment study).
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import torch

from common import (CKPT, HERE, RESULT_SCHEMA, RESULTS, GpuClock, Owner, binom_cdf, cached, clopper_pearson, device,
                    env_info, load_config, log, stats, write_json)
from sigil import attacks as A
from sigil import protocol as P
from sigil import triggerset as TS
from suite import recipe
from wm_core import Net, load_mnist

MEAN, STD = [0.1307], [0.3081]


def fpr_block(errors: list[int], T: int, max_err: int) -> dict:
    n = len(errors)
    k = int(sum(e <= max_err for e in errors))
    return {"n": n, "false_positives": k, "fpr": k / n if n else None, "cp95_upper": clopper_pearson(k, n)[1],
            "binomial_reference": binom_cdf(max_err, T), "errors": stats(errors), "min_errors": int(min(errors)),
            "binomial_mean": T / 2, "binomial_std": (T / 4) ** 0.5,
            "histogram": {int(v): int(c) for v, c in zip(*np.unique(errors, return_counts=True))}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "mnist_nulls.yaml"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    dev = device()
    A.deterministic(True)
    env = env_info(dev)
    d = load_mnist(dev)
    clock = GpuClock()
    t0 = time.time()

    nulls = []
    for i in range(cfg["null_models"]):
        def go(i=i):
            torch.manual_seed(5000 + i)
            log(f"train null {i}")
            return A.fit(Net().to(dev), d["x_owner"], d["y_owner"], recipe(cfg["owner_training"], 5000 + i))
        with clock:
            nulls.append(cached(CKPT / f"mnist_null_{i}.pt", Net, go, dev)[0])
    with clock:
        null_acc = [A.accuracy(m, d["x_test"], d["y_test"]) for m in nulls]
    vecs = [A.uchida_vector(m.conv2.weight).detach().double().cpu().numpy() for m in nulls]
    clean = []
    for s in cfg["owner_seeds"]:
        f = CKPT / f"mnist_clean_s{s}.pt"
        if f.exists():
            m = Net().to(dev)
            m.load_state_dict(torch.load(f, map_location=dev, weights_only=True))
            clean.append(A.uchida_vector(m.conv2.weight).detach().double().cpu().numpy())

    out = {"schema": RESULT_SCHEMA, "experiment": "mnist_nulls", "config": cfg, "env": env,
           "null_accuracy": stats(null_acc), "configs": {}}
    for c in cfg["configs"]:
        pcfg = P.Config(T=c["T"], M=c["M"], layer=c["layer"], max_err=c["max_err"])
        owners = [Owner(f"m5/mnist/owner/{s}", pcfg) for s in cfg["owner_seeds"]]
        errs = [o.detect(v).errors for o in owners for v in vecs]
        block = {"protocol_config": pcfg.to_dict(),
                 "owner_key_vs_nulls": fpr_block(errs, c["T"], c["max_err"]),
                 "per_owner_errors": {str(s): [o.detect(v).errors for v in vecs] for s, o in zip(cfg["owner_seeds"], owners)}}
        if clean:
            block["owner_key_vs_clean_models"] = fpr_block([o.detect(v).errors for o in owners for v in clean],
                                                           c["T"], c["max_err"])
        out["configs"][f"T{c['T']}"] = block
        log(f"T={c['T']}: {block['owner_key_vs_nulls']['false_positives']}/{len(errs)} null pairs accepted, "
            f"errors {block['owner_key_vs_nulls']['errors']}")

    # common mode: unrelated networks' Uchida vectors share a mean component mu, so X @ w ~ mu * rowsum(X) and the
    # extracted bits for a fixed key are largely predictable: bit_i ~ [mu * rowsum_i >= 0]. For a fixed owner key the
    # null errors therefore cluster around the distance between b and that pattern (a per-key quantity).
    pcfg = P.Config()
    cm_rows = []
    for v in vecs:
        cm_rows.append(float(v.mean() / v.std()))
    pattern_dist, predicted_share = {}, []
    for s in cfg["owner_seeds"]:
        o = Owner(f"m5/mnist/owner/{s}", pcfg)
        rs = o.X.astype(np.int64).sum(1)
        for v in vecs:
            bits = (o.X.astype(np.float64) @ v >= 0).astype(np.uint8)
            pred = ((np.sign(v.mean()) * rs) >= 0).astype(np.uint8)
            predicted_share.append(float((bits == pred).mean()))
        pattern_dist[str(s)] = {"neg_mean": int(((rs <= 0).astype(np.uint8) != o.b).sum()),
                                "pos_mean": int(((rs >= 0).astype(np.uint8) != o.b).sum())}
    out["common_mode"] = {
        "mean_over_std_of_null_vectors": stats(cm_rows),
        "share_of_bits_predicted_by_rowsum_sign": stats(predicted_share),
        "owner_signature_distance_to_common_mode_pattern": pattern_dist,
        "note": "errors of a null model against a fixed key cluster near this distance; P[distance <= max_err] over "
                "random keys is P[Bin(T, 1/2) <= max_err], so the pooled multi-key study, not the per-key one, bounds the FPR",
    }
    log(f"common mode: {out['common_mode']}")

    # pooled: many independent (seed, owner key) pairs against every null, T=64
    W = np.stack([P.quantize(v, pcfg) for v in vecs])              # (nulls, M) int64
    pooled = []
    for j in range(cfg["pooled_keys"]):
        o = Owner(f"m5/mnist/nullkey/{j}", pcfg)
        bits = (o.X.astype(np.int64) @ W.T >= 0).astype(np.uint8)  # (T, nulls)
        pooled += (bits != o.b[:, None]).sum(0).tolist()
    out["pooled_T64"] = fpr_block(pooled, pcfg.T, pcfg.max_err)
    log(f"pooled: {out['pooled_T64']['false_positives']}/{len(pooled)}")

    # realignment: does matching a null's channels to the owner's model make it look watermarked?
    if cfg.get("realign_against_owner"):
        rerr = []
        for s in cfg["owner_seeds"]:
            f = CKPT / f"mnist_wm_s{s}.pt"
            if not f.exists():
                continue
            ref = Net().to(dev)
            ref.load_state_dict(torch.load(f, map_location=dev, weights_only=True))
            o = Owner(f"m5/mnist/owner/{s}", pcfg)
            for m in nulls:
                r, _, _ = A.realign(m, ref, "conv1", "conv2")
                rerr.append(o.detect(A.uchida_vector(r.conv2.weight).detach().double().cpu().numpy()).errors)
        if rerr:
            out["realigned_nulls_T64"] = fpr_block(rerr, pcfg.T, pcfg.max_err)
            log(f"realigned nulls: {out['realigned_nulls_T64']['errors']}")

    # trigger set: null models' matches on each owner's committed trigger set
    tsc = cfg["triggerset"]
    spec = TS.Spec(n=tsc["n"], shape=(1, 28, 28), num_classes=10, grid=tsc["grid"])
    k = TS.threshold(spec.n, 10, tsc["fpr"])
    matches = []
    for s in cfg["owner_seeds"]:
        o = Owner(f"m5/mnist/owner/{s}", pcfg)
        ts = TS.derive(o.seed, o.pkh, spec)
        with clock:
            matches += [TS.verify(TS.torch_predictor(m), ts, MEAN, STD, k=k).matches for m in nulls]
    n = len(matches)
    fp = sum(mm >= k for mm in matches)
    out["triggerset"] = {"threshold": k, "n_triggers": spec.n, "pairs": n, "false_positives": fp,
                         "cp95_upper": clopper_pearson(fp, n)[1], "binomial_reference": TS.binom_sf(k, spec.n, 0.1),
                         "matches": stats(matches), "max_matches": int(max(matches)),
                         "histogram": {int(v): int(c) for v, c in zip(*np.unique(matches, return_counts=True))}}
    log(f"trigger nulls: {fp}/{n}, matches {out['triggerset']['matches']}")
    out["gpu_seconds"] = round(clock.seconds, 1)
    out["wall_seconds"] = round(time.time() - t0, 1)
    write_json(RESULTS / "mnist_nulls.json", out)
    log("done -> results/mnist_nulls.json")


if __name__ == "__main__":
    main()
