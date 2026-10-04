"""Run the whole demo storyline: env check -> (train) -> attacks -> forgery -> committed seed.

  python run_all.py            # reuse checkpoints if present (fast, for the live demo)
  python run_all.py --retrain  # retrain everything first
  python run_all.py --pause    # wait for Enter between demos (presenter mode)
  python run_all.py --ezkl     # also run the ZK demos (owner + thief proofs, VK cross-check; ~15 s)
  python run_all.py --ezkl --hashed   # plus Poseidon-committed proofs (~1.5 min each, ~10 GB temp pk)

Everything printed is also written to results/run_log.txt.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from demo_common import child_env, is_noise

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--retrain", action="store_true")
ap.add_argument("--pause", action="store_true")
ap.add_argument("--tries", type=int, default=20000)
ap.add_argument("--ezkl", action="store_true")
ap.add_argument("--hashed", action="store_true")
args = ap.parse_args()

steps = [("00_env_check.py", [])]
if args.retrain or not (ROOT / "ckpt" / "watermarked.pt").exists():
    steps.append(("01_train.py", []))
steps += [("02_attacks.py", []), ("03_forgery.py", []), ("04_committed_seed.py", ["--tries", str(args.tries)])]
if args.ezkl:
    steps += [("05_ezkl_spike.py", ["--vis", "private", "--who", "owner"]),
              ("05_ezkl_spike.py", ["--vis", "private", "--who", "thief"]),
              ("06_vk_crosscheck.py", [])]
    if args.hashed:
        steps += [("05_ezkl_spike.py", ["--vis", "hashed", "--who", "owner"]),
                  ("05_ezkl_spike.py", ["--vis", "hashed", "--who", "thief"])]
    steps += [("07_commitment_summary.py", [])]
(ROOT / "results").mkdir(exist_ok=True)
t_all = time.time()
with open(ROOT / "results" / "run_log.txt", "w", encoding="utf-8") as log:
    for script, extra in steps:
        if args.pause and script != "00_env_check.py":
            input(f"\n>>> Press Enter to run {script} ...")
        proc = subprocess.Popen([sys.executable, "-u", script, *extra], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                env=child_env())
        for line in proc.stdout:
            log.write(line)
            if not is_noise(line):
                sys.stdout.write(line)
        if proc.wait() != 0:
            sys.exit(f"\n{script} failed (exit {proc.returncode})")
    msg = f"\nAll demos finished in {time.time() - t_all:.0f}s. Log: results/run_log.txt\n"
    print(msg)
    log.write(msg)
