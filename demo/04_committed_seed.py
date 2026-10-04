"""DEMO D: the fix. Commit to a secret seed at embedding time and derive BOTH the key
and the signature from it (01 report, section 7).

D0  Owner opens the published commitment and verifies ownership.
D1  Naive fix: key derived from a committed seed, signature chosen freely.
    Thief: pick any seed', derive X', SET sig' := extract(X', W), commit after the theft.
D2  Real fix: signature also derived from the seed. The thief can only search seeds
    and hope extraction happens to match: an adaptive search, measured over N tries.
Null check: owner's key on independently trained models (indicative only, not a calibrated FPR).
"""
import argparse
import hashlib
import math
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

from wm_core import (RESULTS, T_BITS, THETA, THIEF_ID, banner, ber, binom_tail_le, commitment,
                     derive_key, derive_signature, device, extract_bits, load_model, load_owner,
                     null_model_names, utc_now, wm_vector)

ap = argparse.ArgumentParser()
ap.add_argument("--tries", type=int, default=20000, help="thief's seed-search budget in D2")
ap.add_argument("--d1", type=int, default=1000, help="trials for the naive-fix attack in D1")
args = ap.parse_args()

dev = device()
seed, secret, public, X, b = load_owner(dev)
stolen = load_model("watermarked", dev)
w = wm_vector(stolen).detach().cpu().numpy()
k = math.floor(THETA * T_BITS)

banner("DEMO D0: Owner opens the commitment published at embedding time")
ok_commit = commitment(seed, secret["owner_id"]) == public["commitment_sha256"]
e_owner = ber(extract_bits(stolen, X), b)
print(f"  Published commitment : {public['commitment_sha256'][:32]}...  ({public['timestamp_utc']})")
print(f"  H(seed || owner_id)  : {'MATCHES' if ok_commit else 'MISMATCH'}")
print(f"  BER on stolen model  : {e_owner:.3f}  -> {'OWNERSHIP VERIFIED' if ok_commit and e_owner <= THETA else 'FAIL'}")

banner("DEMO D1: Naive fix (only the key is derived; signature is a free choice)")
wins = 0
for i in range(args.d1):
    s = hashlib.sha256(b"thief-d1|" + i.to_bytes(8, "big")).digest()
    Xt = derive_key(s)
    sig = (Xt @ w >= 0).astype(np.uint8)          # thief SETS the signature to what X' extracts
    wins += int(np.mean((Xt @ w >= 0) != sig) <= THETA)
s0 = hashlib.sha256(b"thief-d1|" + (0).to_bytes(8, "big")).digest()
print(f"  Thief forgeries accepted : {wins}/{args.d1}  ({100 * wins / args.d1:.0f}%)")
print(f"  Example thief commitment : {commitment(s0, THIEF_ID)[:32]}...  (made {utc_now()}, after the theft)")
print("  -> Only timestamp ordering separates owner from thief. A theft before the owner")
print("     commits (e.g. a dev-time leak) would defeat even that.")

banner(f"DEMO D2: Real fix (key AND signature derived from the seed); thief searches {args.tries:,} seeds")
t0 = time.time()
bers = np.empty(args.tries)
for i in range(args.tries):
    s = hashlib.sha256(b"thief-d2|" + i.to_bytes(8, "big")).digest()
    bits = (derive_key(s) @ w >= 0).astype(np.uint8)
    bers[i] = np.mean(bits != derive_signature(s, THIEF_ID))
dt = time.time() - t0
hits = int(np.sum(bers <= THETA))
p = binom_tail_le(T_BITS, k)
print(f"  Search time              : {dt:.1f}s ({args.tries / dt:,.0f} seeds/s)")
print(f"  Best BER the thief found : {bers.min():.3f}   (mean {bers.mean():.3f})")
print(f"  Forgeries accepted       : {hits}/{args.tries:,}  at threshold BER <= {THETA:.3f}")
print(f"  Theory, per try          : P[Bin({T_BITS},0.5) <= {k}] = {p:.2e}  -> expected {args.tries * p:.2e} hits")
need = math.log(2) / p
print(f"  Work factor              : ~2^{math.log2(1 / p):.1f} seeds (~{need:.1e} for a 50% chance)")
print(f"                             = ~{need / (args.tries / dt) / 3600:,.0f} single-core hours at this rate:")
print("                             feasible on a GPU or cluster. Hence timestamps still matter,")
print("                             and RQ1 must set signature length T and threshold theta.")
p256 = binom_tail_le(256, 32)
print(f"  Target level (T=256 bits, as in Uchida; same theta=1/8): ~2^{math.log2(1 / p256):.0f} per try")

banner("NULL CHECK: owner's key on models that were never watermarked (indicative only)")
for n in null_model_names():
    print(f"  {n:<8} BER = {ber(extract_bits(load_model(n, dev), X), b):.3f}")
print("  A handful of null models is not enough to state a false-positive rate; that is Phase 1 work.")

fig, ax = plt.subplots(figsize=(7.5, 4))
ax.hist(bers, bins=np.arange(-0.5, T_BITS + 1.5) / T_BITS, color="#4c72b0", label="thief, D2 seed search")
ax.axvline(THETA, ls="--", c="crimson", label=f"acceptance threshold {THETA:.3f}")
ax.axvline(e_owner, c="green", lw=3, label=f"owner BER {e_owner:.3f}")
ax.set_xlabel("BER of extracted vs derived signature")
ax.set_ylabel("number of seeds tried")
ax.set_title(f"Committed-seed scheme: {args.tries:,} forgery attempts, {hits} accepted")
ax.legend()
fig.tight_layout()
fig.savefig(RESULTS / "forgery_search.png", dpi=150)
print("\n  Saved results/forgery_search.png")

# ---- structured results for the web UI (additive)
from demo_common import current_commitment, write_json
counts, _ = np.histogram(bers, bins=np.arange(-0.5, T_BITS + 1.5) / T_BITS)
write_json("committed_seed.json", {
    "commitment": current_commitment(), "threshold": THETA, "signature_bits_T": T_BITS,
    "d0": {"commitment_matches": bool(ok_commit), "owner_ber": e_owner, "verified": bool(ok_commit and e_owner <= THETA),
           "timestamp_utc": public["timestamp_utc"]},
    "d1": {"wins": wins, "trials": args.d1},
    "d2": {"tries": args.tries, "seconds": dt, "seeds_per_s": args.tries / dt, "min_ber": float(bers.min()),
           "mean_ber": float(bers.mean()), "accepted": hits, "p_per_try": p, "log2_work": math.log2(1 / p),
           "seeds_for_half": need, "single_core_hours": need / (args.tries / dt), "log2_work_T256": math.log2(1 / p256),
           "histogram": [{"ber": i / T_BITS, "count": int(c)} for i, c in enumerate(counts)]},
    "nulls": [{"model": n, "owner_ber": ber(extract_bits(load_model(n, dev), X), b)} for n in null_model_names()],
})
