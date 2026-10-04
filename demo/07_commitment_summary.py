"""DEMO E3: the fix inside the ZK proof. With params 'hashed', EZKL exposes a Poseidon hash of
the private key+signature as a public value. The owner publishes that hash at embedding time;
a verifier accepts a proof only if its public hash matches the published one.
Reads precomputed runs of: 05_ezkl_spike.py --vis hashed --who owner|thief (~1.5 min each)."""
import json

from wm_core import RESULTS, banner

banner("DEMO E3: Poseidon-committed proofs (precomputed: 05_ezkl_spike.py --vis hashed)")
try:
    own = json.loads((RESULTS / "ezkl_hashed_owner" / "summary.json").read_text())
    thf = json.loads((RESULTS / "ezkl_hashed_thief" / "summary.json").read_text())
except FileNotFoundError:
    raise SystemExit("  (not available: run 05_ezkl_spike.py --vis hashed --who owner / thief first)")
published = own["param_commitment_poseidon"][0][0]
print(f"  Owner's Poseidon commitment : {published}")
print("    (in the protocol: published at embedding time; in this demo: taken from the owner's run)")
for who, s in [("owner", own), ("thief", thf)]:
    h = s["param_commitment_poseidon"][0][0]
    verdict = "ACCEPT" if s["verified"] and h == published else "REJECT (hash != published commitment)"
    print(f"  {who:<5} proof verifies={s['verified']}  score={s['public_outputs'][0][0]}  hash={h[:18]}...  -> {verdict}")
print("\n  Scope: this commits to (X, s) directly, i.e. the D1 level. A thief who fits a key AFTER the")
print("  theft and publishes their own hash is stopped only by timestamp ordering. Reaching D2 inside")
print("  the proof (deriving X and s from the committed seed in-circuit) is Phase 3 work.")
print("  Not yet linked: the SHA-256 seed commitment (demos A/D) and this Poseidon (X, s) commitment.")
print(f"  The hash covers params quantised at the calibrated scale, so a real commitment must also pin")
print(f"  the circuit settings at embedding time.")
print(f"\n  Cost of committing (vs uncommitted, logrows 15): logrows {own['logrows']}, prove {own['seconds']['prove']:.1f}s, "
      f"verify {own['seconds']['verify'] * 1000:.0f} ms, proof {own['proof_bytes'] / 1024:.1f} KB, "
      f"pk {own['pk_bytes'] / 2**30:.1f} GiB, sampled peak RAM {own['peak_rss_bytes'] / 2**30:.2f} GiB")
