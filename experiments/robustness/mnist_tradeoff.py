"""ROB-07 trade-off on MNIST: accuracy cost (vs the same-seed clean model) and robustness vs lambda and T.

Robustness probes per watermarked model: 90% magnitude pruning, FTAL (5 epochs) and overwriting with the
thief's own key; each reports the owner's errors/BER and survival at max_err = T/8. WM-09's MNIST target
(<= 0.5 pp at T = 256) is read off the same table.

    python experiments/robustness/mnist_tradeoff.py
Writes results/mnist_tradeoff.json and .csv (reuses mnist_matrix checkpoints where identical).
"""
from __future__ import annotations

import argparse
import time

import torch

from common import CKPT, HERE, RESULT_SCHEMA, RESULTS, GpuClock, Owner, cached, device, env_info, load_config, log, stats, write_csv, write_json
from sigil import attacks as A
from sigil import protocol as P
from suite import Context, plan, recipe
from wm_core import Net, load_mnist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "mnist_tradeoff.yaml"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    dev = device()
    A.deterministic(True)
    env = env_info(dev)
    d = load_mnist(dev)
    clock = GpuClock()
    t0 = time.time()
    rows = []
    for s in cfg["seeds"]:
        def train(name, reg=None, s=s):
            def go():
                torch.manual_seed(1000 + s)
                log(f"train {name}")
                return A.fit(Net().to(dev), d["x_owner"], d["y_owner"], recipe(cfg["owner_training"], 1000 + s), regularizer=reg)
            with clock:
                return cached(CKPT / f"{name}.pt", Net, go, dev)[0]

        clean = train(f"mnist_clean_s{s}")
        with clock:
            clean_acc = A.accuracy(clean, d["x_test"], d["y_test"])
        for T in cfg["Ts"]:
            pcfg = P.Config(T=T, M=cfg["M"], layer=cfg["layer"], max_err=T // 8)
            owner = Owner(f"m5/mnist/owner/{s}", pcfg)
            thief = Owner(f"m5/mnist/thief/{s}", pcfg)
            ctx = Context(layer=cfg["layer"], producer="conv1", fineprune_layer=cfg["layer"], x_att=d["x_att"],
                          y_att=d["y_att"], x_calib=d["x_att"][:2000], thief_X=thief.X, thief_b=thief.b,
                          student=lambda sd: Net().to(dev), seed=100 + s)
            for lam in cfg["lams"]:
                name = f"mnist_wm_s{s}" if (T == 64 and lam == 1.0) else f"mnist_T{T}_lam{lam}_s{s}"
                m = train(name, A.uchida_regularizer(cfg["layer"], owner.X, owner.b, lam))
                vec = lambda mm: A.uchida_vector(mm.conv2.weight).detach().double().cpu().numpy()  # noqa: E731
                with clock:
                    acc = A.accuracy(m, d["x_test"], d["y_test"])
                det = owner.detect(vec(m))
                rec = {"seed": s, "T": T, "lam": lam, "max_err": pcfg.max_err, "acc": acc, "clean_acc": clean_acc,
                       "acc_cost_pp": (clean_acc - acc) * 100, "errors": det.errors, "ber": det.ber}
                for row in plan(cfg["attacks"], ctx):
                    if row["family"] == "baseline" or row["name"].startswith(("FTLL", "RTLL", "RTAL")):
                        continue
                    key = {"prune": "prune90", "fine-tune": "ftal", "overwrite": "overwrite"}[row["family"]]
                    with clock:
                        attacked, _ = row["run"](m)
                        a_acc = A.accuracy(attacked, d["x_test"], d["y_test"])
                    e = owner.detect(vec(attacked))
                    rec.update({f"{key}_errors": e.errors, f"{key}_ber": e.ber, f"{key}_survived": e.accepted,
                                f"{key}_acc": a_acc})
                rows.append(rec)
                log(f"s{s} T={T} lam={lam}: acc={acc:.4f} cost={rec['acc_cost_pp']:+.2f}pp err={det.errors} "
                    f"prune90={rec['prune90_errors']} ftal={rec['ftal_errors']} overwrite={rec['overwrite_errors']}")
    summary = []
    for T in cfg["Ts"]:
        for lam in cfg["lams"]:
            rs = [r for r in rows if r["T"] == T and r["lam"] == lam]
            summary.append({"T": T, "lam": lam, "n": len(rs), "acc_cost_pp": stats([r["acc_cost_pp"] for r in rs]),
                            "acc": stats([r["acc"] for r in rs]), "ber": stats([r["ber"] for r in rs]),
                            **{f"{k}_ber": stats([r[f"{k}_ber"] for r in rs]) for k in ("prune90", "ftal", "overwrite")},
                            **{f"{k}_survived": sum(r[f"{k}_survived"] for r in rs) for k in ("prune90", "ftal", "overwrite")},
                            "owner_ber0": sum(r["errors"] == 0 for r in rs)})
    write_json(RESULTS / "mnist_tradeoff.json", {"schema": RESULT_SCHEMA, "experiment": "mnist_tradeoff", "config": cfg,
                                                 "seeds": cfg["seeds"], "env": env, "rows": rows, "summary": summary,
                                                 "gpu_seconds": round(clock.seconds, 1),
                                                 "wall_seconds": round(time.time() - t0, 1)})
    write_csv(RESULTS / "mnist_tradeoff.csv", rows)
    log("done -> results/mnist_tradeoff.json")


if __name__ == "__main__":
    main()
