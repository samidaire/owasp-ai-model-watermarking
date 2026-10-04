"""DEMO F: protocol v2 end to end (sigil SDK + Circom/SnarkJS Groth16).

What it shows (docs/protocol.md):
  F1  owner: Ed25519 identity, committed seed, watermark embedded, signed registration + registry receipt
  F2  verifier opens a claim (fresh nonce); owner proves ownership in zero knowledge; verifier accepts
  F3  thief with the stolen weights cannot produce a proof (own seed and key: too many bits wrong;
      owner's commitment: can't open it)
  F4  replayed proof, proof checked against another model, tampered proof: each rejected with its reason
  F5  robustness in ZK: proofs after pruning / fine-tuning; permutation removes the white-box mark
  F6  overwriting: the thief embeds and registers their own mark later; both proofs verify on the
      overwritten copy and the earlier registry timestamp decides the dispute

The demo owner/registry keys and seed live in ckpt/v2/, encrypted with the PUBLIC demo passphrase
below, committed on purpose so the saved results reproduce (like ckpt/owner_secret.json for v1).
Writes results/protocol_v2.json and the owner's public proof bundle in results/protocol_v2/.

    python 08_protocol_v2.py            # reuse the saved v2 identity and model; ~1 min with a GPU
    python 08_protocol_v2.py --retrain  # new owner identity, seed and watermarked model
"""
import argparse
import copy
import hashlib
import json
import time

import numpy as np
import torch
import torch.nn as nn

from demo_common import write_json
from wm_core import CKPT, RESULTS, Net, accuracy, banner, device, load_mnist, train

from sigil import protocol as P
from sigil import secretbox
from sigil.adapters import uchida_vector
from sigil.adapters.torch_adapter import finetune_embed
from sigil.identity import KeyPair
from sigil.records import make_claim, make_receipt, make_registration, registration_hash
from sigil.verify import verify_ownership
from sigil.zk import circom as Z

DEMO_PASS = "sigil-demo-only-passphrase"        # PUBLIC: demo identities only, never for real keys
V2 = CKPT / "v2"
OUT = RESULTS / "protocol_v2"
CFG = P.Config()                                # T=64, M=288, conv2, theta = 8/64

ap = argparse.ArgumentParser()
ap.add_argument("--retrain", action="store_true")
ap.add_argument("--epochs", type=int, default=3)
args = ap.parse_args()
dev = device()
d = load_mnist(dev)


def sha256_file(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(model, name):
    p = V2 / f"{name}.pt"
    torch.save(model.state_dict(), p)
    return p


def load(name):
    m = Net().to(dev)
    m.load_state_dict(torch.load(V2 / f"{name}.pt", map_location=dev, weights_only=True))
    return m.eval()


def wvec(model_or_path):
    return uchida_vector(model_or_path, CFG.layer)


def try_prove(seed, pkh, w, nonce):
    """Returns (proof, public, timing) or (None, reason, None) when no valid witness exists."""
    w_q = P.quantize(w, CFG)
    det = P.detect(seed, pkh, CFG, w_q)
    if not det.accepted:
        return None, f"no proof possible: {det.errors}/{CFG.T} bits wrong (> {CFG.max_err})", det
    try:
        return (*Z.prove(CFG, P.circuit_input(seed, w_q, pkh, CFG, nonce))[:3],)
    except Z.ZkError as e:
        return None, f"no proof possible: {str(e).splitlines()[0]}", det


def verdict(proof, public, reg, rcp, claim, suspect_path, trusted):
    return verify_ownership(proof=proof, public=public, registration=reg, receipt=rcp, claim=claim,
                            suspect_w=wvec(suspect_path), suspect_model_sha256=sha256_file(suspect_path),
                            trusted_registry_keys=trusted).to_dict()


V2.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
art = Z.artifacts(CFG)
if not art.zkey.exists():
    raise SystemExit(f"circuit not set up: run `sigil zk-setup` (needs {art.zkey.name})")

# ------------------------------------------------------------------ F1: owner identity, embedding, registration
banner("DEMO F1: owner identity, committed seed, watermark, signed registration")
if args.retrain or not (V2 / "owner.key").exists():
    owner, registry = KeyPair.generate(), KeyPair.generate()
    owner.save(V2 / "owner.key", DEMO_PASS)
    registry.save(V2 / "registry.key", DEMO_PASS)
    seed = P.new_seed()
    secretbox.save(V2 / "seed.json", {"seed": str(seed), "config": CFG.to_dict()}, DEMO_PASS, "seed")
    pkh = P.pk_hash(owner.public_bytes)
    torch.manual_seed(1)
    wm = Net().to(dev)
    X, b = P.key_matrix(seed, pkh, CFG).astype(np.float32), P.signature_bits(seed, pkh, CFG)
    finetune_embed(wm, (d["x_owner"], d["y_owner"]), X, b, args.epochs, layer=CFG.layer, lam=1.0,
                   device=dev, seed=1)
    del X, b
    wm_path = save(wm.eval(), "watermarked_v2")
    reg = make_registration(owner, seed, CFG, sha256_file(wm_path))
    time.sleep(1.1)
    rcp = make_receipt(registry, reg)
    json.dump(reg, open(V2 / "registration.json", "w"), indent=2)
    json.dump(rcp, open(V2 / "receipt.json", "w"), indent=2)
else:
    owner, registry = KeyPair.load(V2 / "owner.key", DEMO_PASS), KeyPair.load(V2 / "registry.key", DEMO_PASS)
    seed = int(secretbox.load(V2 / "seed.json", DEMO_PASS, "seed")["seed"])
    pkh = P.pk_hash(owner.public_bytes)
    wm_path = V2 / "watermarked_v2.pt"
    reg = json.load(open(V2 / "registration.json"))
    rcp = json.load(open(V2 / "receipt.json"))
wm = load("watermarked_v2")
clean_path = CKPT / "clean.pt"
trusted = {registry.public_hex}
det_owner = P.detect(seed, pkh, CFG, wvec(wm_path))
print(f"  owner public key   : {owner.public_hex[:16]}…   commitment C = {reg['commitment'][:20]}…")
print(f"  registry receipt   : {rcp['registered_at']}")
print(f"  accuracy           : watermarked {accuracy(wm, d['x_test'], d['y_test']):.4f}")
print(f"  owner detection    : {det_owner.errors}/{CFG.T} bits wrong -> {'ACCEPT' if det_owner.accepted else 'REJECT'}")

# ------------------------------------------------------------------ F2: claim, proof, verification
banner("DEMO F2: verifier opens a claim; owner proves in zero knowledge; verifier checks everything")
time.sleep(1.1)
claim = make_claim(reg, sha256_file(wm_path))
proof, public, timing = try_prove(seed, pkh, wvec(wm_path), int(claim["nonce"]))
assert proof is not None, public
v_owner = verdict(proof, public, reg, rcp, claim, wm_path, trusted)
for name, obj in (("proof.json", proof), ("public.json", public), ("claim.json", claim),
                  ("registration.json", reg), ("receipt.json", rcp)):
    json.dump(obj, open(OUT / name, "w"), indent=2)
print(f"  witness {timing['witness_s']:.2f} s, prove {timing['prove_s']:.2f} s  ->  "
      f"{'ACCEPTED' if v_owner['accepted'] else 'REJECTED ' + '; '.join(v_owner['reasons'])}")

# ------------------------------------------------------------------ F3: thief
banner("DEMO F3: the thief holds the stolen weights but not the seed")
thief = KeyPair.generate()
tseed, tpkh = P.new_seed(), P.pk_hash(thief.public_bytes)
_, thief_own_reason, det_thief = try_prove(tseed, tpkh, wvec(wm_path), int(claim["nonce"]))
forged = P.circuit_input(tseed, P.quantize(wvec(wm_path), CFG), pkh, CFG, int(claim["nonce"]))
forged["commitment"] = reg["commitment"]
try:
    Z.prove(CFG, forged)
    thief_open_reason = "UNEXPECTED: proof produced"
except Z.ZkError:
    thief_open_reason = "no proof possible: the thief can't open the owner's commitment"
print(f"  own seed and key on the stolen model : {thief_own_reason}")
print(f"  owner's commitment, thief's seed     : {thief_open_reason}")

# ------------------------------------------------------------------ F4: misuse of a valid proof
banner("DEMO F4: a valid proof used the wrong way is rejected, with the reason")
other_claim = make_claim(reg, sha256_file(wm_path))
tampered = copy.deepcopy(proof)
tampered["pi_a"][0] = str(int(tampered["pi_a"][0]) + 1)
misuse = {
    "replayed for another claim": verdict(proof, public, reg, rcp, other_claim, wm_path, trusted),
    "checked against a different model": verdict(proof, public, reg, rcp, dict(claim, suspect_model_sha256=sha256_file(clean_path)),
                                                 clean_path, trusted),
    "tampered proof bytes": verdict(tampered, public, reg, rcp, claim, wm_path, trusted),
    "receipt from an untrusted registry": verdict(proof, public, reg, make_receipt(KeyPair.generate(), reg), claim,
                                                  wm_path, trusted),
}
for k, v in misuse.items():
    print(f"  {k:<36}: {'ACCEPTED (unexpected!)' if v['accepted'] else 'REJECTED: ' + v['reasons'][0]}")


# ------------------------------------------------------------------ F5: robustness in ZK
banner("DEMO F5: does the proof survive removal attacks?")
def prune(model, ratio):
    m = copy.deepcopy(model)
    with torch.no_grad():
        for mod in m.modules():
            if isinstance(mod, (nn.Conv2d, nn.Linear)):
                w = mod.weight
                w[w.abs() <= w.abs().flatten().kthvalue(int(ratio * w.numel())).values] = 0
    return m


def permute(model):
    m = copy.deepcopy(model)
    perm = torch.randperm(m.conv1.out_channels, generator=torch.Generator().manual_seed(0)).to(dev)
    with torch.no_grad():
        m.conv1.weight.copy_(m.conv1.weight[perm])
        m.conv1.bias.copy_(m.conv1.bias[perm])
        m.conv2.weight.copy_(m.conv2.weight[:, perm])
    return m


attacked = {"prune 65%": prune(wm, 0.65), "prune 90%": prune(wm, 0.90),
            "fine-tune all layers, 5 epochs": train(copy.deepcopy(wm), d["x_att"], d["y_att"], 5, seed=7, tag="FTAL-5"),
            "feature permutation": permute(wm)}
robust = []
for name, m in attacked.items():
    p = save(m.eval(), "attacked_tmp")
    c = make_claim(reg, sha256_file(p))
    prf, pub, extra = try_prove(seed, pkh, wvec(p), int(c["nonce"]))
    v = verdict(prf, pub, reg, rcp, c, p, trusted) if prf is not None else {"accepted": False, "reasons": [pub]}
    det = P.detect(seed, pkh, CFG, wvec(p))
    robust.append({"attack": name, "accuracy": accuracy(m, d["x_test"], d["y_test"]), "errors": det.errors,
                   "proof_accepted": v["accepted"], "reason": None if v["accepted"] else v["reasons"][0]})
    print(f"  {name:<32} acc={robust[-1]['accuracy']:.4f}  errors={det.errors:>2}/{CFG.T}  "
          f"proof: {'ACCEPTED' if v['accepted'] else 'none — ' + robust[-1]['reason']}")
(V2 / "attacked_tmp.pt").unlink()

# ------------------------------------------------------------------ F6: overwriting and the dispute rule
banner("DEMO F6: the thief overwrites with their own mark and registers it later")
over = copy.deepcopy(wm)
Xt, bt = P.key_matrix(tseed, tpkh, CFG).astype(np.float32), P.signature_bits(tseed, tpkh, CFG)
finetune_embed(over, (d["x_att"], d["y_att"]), Xt, bt, 3, layer=CFG.layer, lam=1.0, device=dev, seed=7)
over_path = save(over.eval(), "thief_overwrite")
thief_reg = make_registration(thief, tseed, CFG, sha256_file(over_path))
time.sleep(1.1)
thief_rcp = make_receipt(registry, thief_reg)
time.sleep(1.1)
dispute = []
for who, s, k, r, rc in (("owner", seed, pkh, reg, rcp), ("thief", tseed, tpkh, thief_reg, thief_rcp)):
    c = make_claim(r, sha256_file(over_path))
    prf, pub, extra = try_prove(s, k, wvec(over_path), int(c["nonce"]))
    v = verdict(prf, pub, r, rc, c, over_path, trusted) if prf is not None else {"accepted": False, "reasons": [pub]}
    dispute.append({"party": who, "registered_at": rc["registered_at"], "errors": P.detect(s, k, CFG, wvec(over_path)).errors,
                    "proof_accepted": v["accepted"]})
    print(f"  {who:<6} registered {rc['registered_at']}  errors={dispute[-1]['errors']:>2}/{CFG.T}  "
          f"proof {'ACCEPTED' if v['accepted'] else 'REJECTED'}")
valid = [x for x in dispute if x["proof_accepted"]]
winner = min(valid, key=lambda x: x["registered_at"])["party"] if valid else None
print(f"  dispute rule (earliest valid registration wins): {winner}")
(V2 / "thief_overwrite.pt").unlink()

# ------------------------------------------------------------------ summary for the UI
summary = {
    "protocol": 2, "config": CFG.to_dict(), "circuit": art.name,
    "owner_public_key": owner.public_hex, "commitment": reg["commitment"], "registration_sha256": registration_hash(reg),
    "registered_at": rcp["registered_at"], "registry_public_key": registry.public_hex,
    "accuracy": {"watermarked_v2": accuracy(wm, d["x_test"], d["y_test"])},
    "owner_detection": det_owner.to_dict(),
    "owner_proof": {"accepted": v_owner["accepted"], "checks": v_owner["checks"], "timing": timing,
                    "public_signals": dict(zip(P.PUBLIC_SIGNALS, public)), "proof_json_bytes": (OUT / "proof.json").stat().st_size},
    "thief": {"own_key": thief_own_reason, "owner_commitment": thief_open_reason, "own_key_errors": det_thief.errors},
    "misuse": {k: {"accepted": v["accepted"], "reasons": v["reasons"]} for k, v in misuse.items()},
    "robustness": robust,
    "overwrite_dispute": {"parties": dispute, "winner": winner},
}
write_json("protocol_v2.json", summary)
banner("DEMO F RESULT")
print(f"  owner proof accepted: {v_owner['accepted']} | thief proof possible: False | misuse rejected: "
      f"{sum(not v['accepted'] for v in misuse.values())}/{len(misuse)} | dispute winner: {winner}")
