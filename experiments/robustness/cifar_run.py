"""CIFAR-10 ResNet-18: watermark cost (WM-09), null calibration (WM-07), attack matrix (ROB-01..03), lambda sweep (ROB-07).

    python experiments/robustness/cifar_run.py train      # clean / T=64 / T=256 models per seed + the dual model
    python experiments/robustness/cifar_run.py nulls      # >= 10 never-watermarked models (fewer epochs)
    python experiments/robustness/cifar_run.py attack     # the attack matrix (+ distillation/extraction on dual)
    python experiments/robustness/cifar_run.py tradeoff   # accuracy and robustness vs lambda at T=256
Checkpoints are cached in experiments/ckpt/robustness/ so phases can be re-run cheaply.
"""
from __future__ import annotations

import argparse
import copy
import json
import time

import numpy as np
import torch

from cifar_common import MEAN, STD, ResNet18, augment, load_cifar
from common import (CKPT, HERE, RESULT_SCHEMA, RESULTS, GpuClock, Owner, binom_cdf, cached, clopper_pearson, device,
                    env_info, load_config, log, stats, write_csv, write_json)
from sigil import attacks as A
from sigil import protocol as P
from sigil import triggerset as TS
from suite import Context, evaluate, plan, recipe

EVAL_BS = 500


def factory():
    return ResNet18().to(memory_format=torch.channels_last)


def halve_batches(obj):
    obj = copy.deepcopy(obj)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "batch_size" and isinstance(v, int):
                    o[k] = max(16, v // 2)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return obj


class Run:
    def __init__(self, cfg_path):
        self.cfg = load_config(cfg_path)
        self.dev = device()
        A.deterministic(False)          # cuDNN autotuning for speed: GPU runs are reproducible up to cuDNN nondeterminism
        self.env = env_info(self.dev)
        self.d = load_cifar(self.dev)
        self.clock = GpuClock()
        w = self.cfg["watermark"]
        self.pcfgs = {c["T"]: P.Config(T=c["T"], M=w["M"], layer=w["layer"], scale_bits=w["scale_bits"],
                                        w_bits=w["w_bits"], max_err=c["max_err"]) for c in w["configs"]}
        tsc = self.cfg["triggerset"]
        self.spec = TS.Spec(n=tsc["n"], shape=(3, 32, 32), num_classes=10, grid=tsc["grid"])
        self.k_ts = TS.threshold(self.spec.n, 10, tsc["fpr"])

    def owner(self, s, T):
        return Owner(f"m5/cifar/owner/{s}", self.pcfgs[T])

    def trigger_set(self, s):
        o = self.owner(s, 256)
        return TS.derive(o.seed, o.pkh, self.spec)

    # ------------------------------------------------------------------ models
    def train_one(self, name, seed, T=None, lam=None, triggers=None, training=None):
        training = training or self.cfg["owner_training"]
        wm = self.cfg["watermark"]

        def go():
            reg = None
            if T is not None:
                o = self.owner(seed, T)
                reg = A.uchida_regularizer(wm["layer"], o.X, o.b, wm["lam"] if lam is None else lam)
            extra = TS.sampler(triggers, MEAN, STD, self.cfg["triggerset"]["per_batch"], self.dev) if triggers else None
            tr = training
            while True:
                torch.manual_seed(2000 + seed if not name.startswith("cifar_null") else seed)
                m = factory().to(self.dev)
                log(f"train {name}")
                try:
                    return A.fit(m, self.d["x_owner"], self.d["y_owner"], recipe(tr, 2000 + seed), regularizer=reg,
                                 extra=extra, augment=augment)
                except torch.cuda.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    tr = halve_batches(tr)
                    log(f"OOM: retrying {name} with batch {tr['batch_size']}")
        with self.clock:
            m, fresh = cached(CKPT / f"{name}.pt", factory, go, self.dev)
        return m.to(memory_format=torch.channels_last)

    def base_models(self, s):
        models = {"clean": self.train_one(f"cifar_clean_s{s}", s)}
        for T in self.pcfgs:
            models[f"T{T}"] = self.train_one(f"cifar_T{T}_s{s}", s, T=T)
        if s in self.cfg["dual"]["seeds"]:
            models["dual"] = self.train_one(f"cifar_dual_s{s}", s, T=self.cfg["dual"]["T"], triggers=self.trigger_set(s))
        return models

    def score(self, m, s, T, ts=None):
        with self.clock:
            return evaluate(m, self.owner(s, T), self.cfg["watermark"]["layer"], self.d["x_test"], self.d["y_test"],
                            ts, MEAN, STD, self.k_ts, bs=EVAL_BS)

    def errors(self, m, s, T):
        w = A.uchida_vector(A.get_module(m, self.cfg["watermark"]["layer"]).weight).detach().double().cpu().numpy()
        return self.owner(s, T).detect(w).errors

    def accuracy(self, m):
        with self.clock:
            return A.accuracy(m, self.d["x_test"], self.d["y_test"], EVAL_BS)

    # ------------------------------------------------------------------ phases
    def phase_train(self):
        rows = []
        for s in self.cfg["seeds"]:
            models = self.base_models(s)
            ts = self.trigger_set(s)
            for kind, m in models.items():
                T = 256 if kind in ("clean", "dual") else int(kind[1:])
                ev = self.score(m, s, T, ts)
                ev_other = {f"errors_T{t}": self.errors(m, s, t) for t in self.pcfgs}
                rows.append({"seed": s, "model": kind, **ev, **ev_other})
                log(f"s{s} {kind}: {rows[-1]}")
        summ = {}
        for kind in dict.fromkeys(r["model"] for r in rows):
            rs = [r for r in rows if r["model"] == kind]
            summ[kind] = {"acc": stats([r["acc"] for r in rs]), "n": len(rs),
                          **{f"errors_T{t}": stats([r[f"errors_T{t}"] for r in rs]) for t in self.pcfgs},
                          "trigger_acc": stats([r["trigger_acc"] for r in rs])}
            if kind != "clean":
                summ[kind]["acc_cost_pp"] = stats([
                    (next(c["acc"] for c in rows if c["seed"] == r["seed"] and c["model"] == "clean") - r["acc"]) * 100
                    for r in rs])
        self.write("cifar_train", {"rows": rows, "summary": summ,
                                   "protocol_configs": {f"T{t}": c.to_dict() for t, c in self.pcfgs.items()}})

    def phase_nulls(self):
        nc = self.cfg["nulls"]
        nulls = [self.train_one(f"cifar_null_{i}", nc["seed_base"] + i, training=nc["training"]) for i in range(nc["count"])]
        with self.clock:
            accs = [A.accuracy(m, self.d["x_test"], self.d["y_test"], EVAL_BS) for m in nulls]
        layer = self.cfg["watermark"]["layer"]
        vecs = [A.uchida_vector(A.get_module(m, layer).weight).detach().double().cpu().numpy() for m in nulls]
        out = {"null_accuracy": stats(accs), "null_training": nc["training"], "configs": {}}
        clean_vecs = []
        for s in self.cfg["seeds"]:
            f = CKPT / f"cifar_clean_s{s}.pt"
            if f.exists():
                m = factory().to(self.dev)
                m.load_state_dict(torch.load(f, map_location=self.dev, weights_only=True))
                clean_vecs.append(A.uchida_vector(A.get_module(m, layer).weight).detach().double().cpu().numpy())
        for T, pcfg in self.pcfgs.items():
            owners = [self.owner(s, T) for s in self.cfg["seeds"]]
            errs = [o.detect(v).errors for o in owners for v in vecs]
            k = sum(e <= pcfg.max_err for e in errs)
            blk = {"protocol_config": pcfg.to_dict(), "n": len(errs), "false_positives": k, "fpr": k / len(errs),
                   "cp95_upper": clopper_pearson(k, len(errs))[1], "binomial_reference": binom_cdf(pcfg.max_err, T),
                   "errors": stats(errs), "min_errors": int(min(errs)), "binomial_mean": T / 2,
                   "binomial_std": (T / 4) ** 0.5}
            if clean_vecs:
                ce = [o.detect(v).errors for o in owners for v in clean_vecs]
                blk["clean_models"] = {"n": len(ce), "false_positives": sum(e <= pcfg.max_err for e in ce),
                                       "errors": stats(ce)}
            # realignment against the owner's own T-model must not manufacture a match
            rerr = []
            for s, o in zip(self.cfg["seeds"], owners):
                f = CKPT / f"cifar_T{T}_s{s}.pt"
                if f.exists():
                    ref = factory().to(self.dev)
                    ref.load_state_dict(torch.load(f, map_location=self.dev, weights_only=True))
                    for m in nulls:
                        r, _, _ = A.realign(m, ref, self.cfg["watermark"]["producer"], layer)
                        rerr.append(o.detect(A.uchida_vector(A.get_module(r, layer).weight).detach().double().cpu().numpy()).errors)
            if rerr:
                blk["realigned_nulls"] = {"n": len(rerr), "false_positives": sum(e <= pcfg.max_err for e in rerr),
                                          "errors": stats(rerr), "min_errors": int(min(rerr))}
            out["configs"][f"T{T}"] = blk
            log(f"nulls T={T}: {blk}")
        matches = []
        for s in self.cfg["seeds"]:
            ts = self.trigger_set(s)
            with self.clock:
                matches += [TS.verify(TS.torch_predictor(m), ts, MEAN, STD, k=self.k_ts).matches for m in nulls]
        fp = sum(mm >= self.k_ts for mm in matches)
        out["triggerset"] = {"threshold": self.k_ts, "pairs": len(matches), "false_positives": fp,
                             "cp95_upper": clopper_pearson(fp, len(matches))[1], "matches": stats(matches),
                             "max_matches": int(max(matches)), "binomial_reference": TS.binom_sf(self.k_ts, self.spec.n, 0.1)}
        self.write("cifar_nulls", out)

    def context(self, s, T):
        thief = Owner(f"m5/cifar/thief/{s}", self.pcfgs[T])
        w = self.cfg["watermark"]

        def student(sd):
            torch.manual_seed(sd)
            return factory().to(self.dev)
        return Context(layer=w["layer"], producer=w["producer"], fineprune_layer="layer4.1.conv2",
                       x_att=self.d["x_att"], y_att=self.d["y_att"], x_calib=self.d["x_att"][:2000],
                       thief_X=thief.X, thief_b=thief.b, student=student, seed=200 + s,
                       augment=augment, query_augment=augment)

    def run_matrix(self, model, s, T, attacks_cfg, kind, ts, rows):
        base = self.score(model, s, T, ts)
        clean_acc = self.accuracy(self.train_one(f"cifar_clean_s{s}", s))
        ctx = self.context(s, T)
        names = [r["name"] for r in plan(attacks_cfg, ctx)]
        for name in names:
            acfg = attacks_cfg
            while True:
                row = next(r for r in plan(acfg, ctx) if r["name"] == name)
                t0 = time.time()
                try:
                    with self.clock:
                        attacked, info = row["run"](model)
                    break
                except torch.cuda.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    acfg = halve_batches(acfg)
                    log(f"OOM in {name}: halving batch sizes")
            ev = self.score(attacked, s, T, ts)
            info.pop("suspect", None)
            info.pop("realign_perm", None)
            rows.append({"seed": s, "model": kind, "T": T, "attack": name, "family": row["family"],
                         "params": json.dumps(row["params"], sort_keys=True), **ev,
                         "acc_drop_pp": round((base["acc"] - ev["acc"]) * 100, 4),
                         "acc_vs_clean_pp": round((clean_acc - ev["acc"]) * 100, 4),
                         "info": json.dumps(info, sort_keys=True), "seconds": round(time.time() - t0, 1)})
            log(f"s{s} {kind:5s} {name:<50s} acc={ev['acc']:.4f} err={ev['errors']:3d}/{T} surv={ev['survived']!s:5s} "
                f"trig={ev.get('trigger_acc', float('nan')):.2f} ({time.time() - t0:.0f}s)")
            del attacked
            torch.cuda.empty_cache()

    def phase_attack(self):
        rows = []
        for s in self.cfg["seeds"]:
            models = self.base_models(s)
            ts = self.trigger_set(s)
            for T in self.pcfgs:
                self.run_matrix(models[f"T{T}"], s, T, self.cfg["attacks"], f"T{T}", ts, rows)
            if "dual" in models:
                self.run_matrix(models["dual"], s, self.cfg["dual"]["T"], self.cfg["dual_attacks"], "dual", ts, rows)
            write_csv(RESULTS / "cifar_matrix.csv", rows)       # partial progress
        summ = {}
        for kind in dict.fromkeys(r["model"] for r in rows):
            for name in dict.fromkeys(r["attack"] for r in rows if r["model"] == kind):
                rs = [r for r in rows if r["model"] == kind and r["attack"] == name]
                summ.setdefault(kind, {})[name] = {
                    "family": rs[0]["family"], "n": len(rs), "acc": stats([r["acc"] for r in rs]),
                    "acc_drop_pp": stats([r["acc_drop_pp"] for r in rs]), "errors": stats([r["errors"] for r in rs]),
                    "ber": stats([r["ber"] for r in rs]), "survived": sum(r["survived"] for r in rs),
                    "trigger_acc": stats([r.get("trigger_acc") for r in rs]),
                    "trigger_accepted": sum(bool(r.get("trigger_accepted")) for r in rs)}
        write_csv(RESULTS / "cifar_matrix.csv", rows)
        self.write("cifar_matrix", {"rows": rows, "summary": summ, "trigger_threshold": self.k_ts,
                                    "protocol_configs": {f"T{t}": c.to_dict() for t, c in self.pcfgs.items()}})

    def phase_tradeoff(self):
        tc = self.cfg["tradeoff"]
        T = tc["T"]
        sweep = {"prune_ratios": [0.9], "finetune": self.cfg["attacks"]["finetune"]}
        rows = []
        for s in tc["seeds"]:
            clean = self.train_one(f"cifar_clean_s{s}", s)
            clean_acc = self.accuracy(clean)
            for lam in tc["lams"]:
                name = f"cifar_T{T}_s{s}" if lam == self.cfg["watermark"]["lam"] else f"cifar_T{T}_lam{lam}_s{s}"
                m = self.train_one(name, s, T=T, lam=lam)
                ev = self.score(m, s, T)
                rec = {"seed": s, "T": T, "lam": lam, "acc": ev["acc"], "acc_cost_pp": (clean_acc - ev["acc"]) * 100,
                       "errors": ev["errors"], "ber": ev["ber"]}
                for row in plan(sweep, self.context(s, T)):
                    if row["family"] == "baseline" or row["name"].startswith(("FTLL", "RTLL", "RTAL")):
                        continue
                    with self.clock:
                        attacked, _ = row["run"](m)
                    e2 = self.score(attacked, s, T)
                    key = "prune90" if row["family"] == "prune" else "ftal"
                    rec.update({f"{key}_errors": e2["errors"], f"{key}_ber": e2["ber"], f"{key}_acc": e2["acc"],
                                f"{key}_survived": e2["survived"]})
                rows.append(rec)
                log(f"tradeoff {rec}")
        self.write("cifar_tradeoff", {"rows": rows})

    def write(self, name, payload):
        out = {"schema": RESULT_SCHEMA, "experiment": name, "config": self.cfg, "seeds": self.cfg["seeds"],
               "env": self.env, **payload, "gpu_seconds": round(self.clock.seconds, 1)}
        write_json(RESULTS / f"{name}.json", out)
        log(f"wrote results/{name}.json (GPU {self.clock.seconds:.0f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["train", "nulls", "attack", "tradeoff", "all"])
    ap.add_argument("--config", default=str(HERE / "cifar.yaml"))
    args = ap.parse_args()
    run = Run(args.config)
    for ph in (["train", "nulls", "attack", "tradeoff"] if args.phase == "all" else [args.phase]):
        getattr(run, f"phase_{ph}")()


if __name__ == "__main__":
    main()
