"""Verify demo F's saved proof live: honestly, or misused (the Verify page's "Try a misuse" buttons).

    python 09_verify_live.py --case honest      # the owner's proof, as saved by demo F
    python 09_verify_live.py --case replay      # the same proof submitted for a NEW claim (fresh nonce)
    python 09_verify_live.py --case model       # the proof checked against a different model file
    python 09_verify_live.py --case tamper      # one number inside the proof changed
    python 09_verify_live.py --case registry    # the registration backed by an untrusted registry's receipt

Reads the bundle demo F saved in results/protocol_v2/ and runs every check of sigil.verify.verify_ownership
against the suspect model file, printing each one. The verifier recomputes the suspect's w_hash from the file
itself and runs the real Groth16 verification (SnarkJS). Nothing is written; takes about a second.
"""
import argparse
import copy
import hashlib
import json
import time

from wm_core import CKPT, RESULTS, banner

from sigil.adapters import uchida_vector
from sigil.identity import KeyPair
from sigil.records import make_claim, make_receipt
from sigil.verify import verify_ownership

BUNDLE = RESULTS / "protocol_v2"
CASES = {
    "honest": ("the owner's proof, as demo F made it", "nothing: this is the honest claim"),
    "replay": ("replayed for another claim", "the verifier opens a NEW claim (fresh nonce); the old proof is resubmitted"),
    "model": ("checked against a different model", "the suspect file is clean.pt, a model that was never watermarked"),
    "tamper": ("tampered proof bytes", "the first number of pi_a is increased by 1"),
    "registry": ("receipt from an untrusted registry", "the registration is timestamped by a registry the verifier doesn't trust"),
}
# Same order and wording as the Verify page's "What gets checked" list.
CHECKS = [
    ("registration_valid", "Registration signed by the owner"),
    ("receipt_valid", "Registry receipt from a trusted registry"),
    ("registered_before_claim", "Registered before the claim"),
    ("claim_matches_registration", "Claim refers to this registration"),
    ("claim_matches_suspect", "Claim refers to this suspect file"),
    ("public_signal_count", "Five public signals"),
    ("public_pk_hash", "Proof is for the owner's key"),
    ("public_config_hash", "Same watermark configuration"),
    ("public_commitment", "Opens the published commitment"),
    ("public_w_hash", "About this exact model (w_hash)"),
    ("public_nonce", "Made for this claim (nonce)"),
    ("snark_valid", "Groth16 proof verifies"),
]

ap = argparse.ArgumentParser()
ap.add_argument("--case", choices=CASES, default="honest")
args = ap.parse_args()


def read(name):
    return json.loads((BUNDLE / name).read_text(encoding="utf-8"))


def sha256_file(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cut(s, n=10):
    s = str(s)
    return s if len(s) <= 2 * n + 1 else f"{s[:n]}…{s[-6:]}"


if not (BUNDLE / "proof.json").exists():
    raise SystemExit("no saved demo F proof: run demo F first (python 08_protocol_v2.py)")
proof, public, claim = read("proof.json"), read("public.json"), read("claim.json")
reg, rcp = read("registration.json"), read("receipt.json")
trusted = {json.loads((RESULTS / "protocol_v2.json").read_text(encoding="utf-8"))["registry_public_key"]}
suspect = CKPT / "v2" / "watermarked_v2.pt"

title, change = CASES[args.case]
banner(f"VERIFY LIVE: {title}")
if args.case == "replay":
    claim = make_claim(reg, sha256_file(suspect))
elif args.case == "model":
    suspect = CKPT / "clean.pt"
    claim = dict(claim, suspect_model_sha256=sha256_file(suspect))
elif args.case == "tamper":
    proof = copy.deepcopy(proof)
    proof["pi_a"][0] = str(int(proof["pi_a"][0]) + 1)
elif args.case == "registry":
    rcp = make_receipt(KeyPair.generate(), reg)
print(f"  what changes   : {change}")
print(f"  suspect file   : {suspect.name}  (sha256 {sha256_file(suspect)[:16]}…)")
print(f"  claim nonce    : {cut(claim['nonce'])}   opened {claim['opened_at']}")
print(f"  proof pi_a[0]  : {cut(proof['pi_a'][0])}")
print(f"  registry       : {'trusted' if rcp['registry_public_key'] in trusted else 'NOT trusted'} ({rcp['registry_public_key'][:16]}…)")
print("\n  Running sigil.verify.verify_ownership (recomputes w_hash from the file, runs SnarkJS)…\n")

t0 = time.perf_counter()
v = verify_ownership(proof=proof, public=public, registration=reg, receipt=rcp, claim=claim,
                     suspect_w=uchida_vector(suspect, "conv2"), suspect_model_sha256=sha256_file(suspect),
                     trusted_registry_keys=trusted).to_dict()
secs = time.perf_counter() - t0
for key, label in CHECKS:
    if key in v["checks"]:
        print(f"  {'[ok]' if v['checks'][key] else '[XX]'}  {label}")
print()
if v["accepted"]:
    print(f"  VERDICT: ACCEPTED: ownership verified in {secs:.2f} s, 0 watermark bits revealed")
else:
    print(f"  VERDICT: REJECTED in {secs:.2f} s")
    for r in v["reasons"]:
        print(f"    reason: {r}")
