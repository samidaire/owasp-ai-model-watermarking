"""ROB-08: does re-running the same config with the same seed give the same output?

Compares every row shared by two mnist_matrix result files (same seed, model and attack) on accuracy,
errors and trigger matches, and writes results/mnist_repro.json.

    python experiments/robustness/mnist_matrix.py --seeds 0 --out mnist_matrix_repro
    python experiments/robustness/repro_check.py results/mnist_matrix.json results/mnist_matrix_repro.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import HERE, RESULT_SCHEMA, RESULTS, write_json

FIELDS = ("acc", "errors", "ber", "survived", "trigger_matches")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("first")
    ap.add_argument("second")
    args = ap.parse_args()
    a, b = (json.loads((HERE / p).read_text(encoding="utf-8")) for p in (args.first, args.second))
    key = lambda r: (r["seed"], r["model"], r["attack"])  # noqa: E731
    rb = {key(r): r for r in b["rows"]}
    shared = [(r, rb[key(r)]) for r in a["rows"] if key(r) in rb]
    diffs = [{"seed": x["seed"], "model": x["model"], "attack": x["attack"],
              **{f: [x.get(f), y.get(f)] for f in FIELDS if x.get(f) != y.get(f)}}
             for x, y in shared if any(x.get(f) != y.get(f) for f in FIELDS)]
    out = {"schema": RESULT_SCHEMA, "experiment": "mnist_repro", "first": {"file": args.first, "env": a["env"]},
           "second": {"file": args.second, "env": b["env"]}, "rows_compared": len(shared),
           "rows_identical": len(shared) - len(diffs), "fields": list(FIELDS), "differences": diffs}
    write_json(RESULTS / "mnist_repro.json", out)
    print(f"{out['rows_identical']}/{out['rows_compared']} rows identical")


if __name__ == "__main__":
    main()
