"""Test one model (the UI's "Model under test"): does it carry the owner's watermark, and can the owner prove it?

    python 10_test_model.py --model watermarked_v2     # ids: python -c "import model_catalogue as m; print(m.ids())"

1. Builds the model: a saved checkpoint, a file from demo/models/, or a stolen copy of the owner's v2 model made
   right now (pruned, quantised, fine-tuned, permuted or overwritten; seeded, so it's the same copy every time).
2. Measures its accuracy on the 10,000 MNIST test images (when it's the demo's network).
3. Reads the watermark from layer conv2 with both owners' keys: protocol v2 (Ed25519 owner) and v1 (owner:yash).
4. If the v2 mark is there, the verifier opens a claim about this exact file (fresh nonce), the owner makes a
   Groth16 proof and the verifier runs every check. If it isn't, no proof can exist and none is made.
Writes results/model_tests/<model>.json for the UI.
"""
import argparse
import copy
import hashlib
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

import model_catalogue as MC
from demo_common import write_json
from wm_core import CKPT, Net, accuracy, banner, derive_key, derive_signature, device, load_mnist, train

from sigil import protocol as P
from sigil import secretbox
from sigil.adapters import uchida_vector
from sigil.adapters.torch_adapter import finetune_embed
from sigil.identity import KeyPair
from sigil.records import make_claim
from sigil.verify import verify_ownership
from sigil.zk import circom as Z

DEMO_PASS = "sigil-demo-only-passphrase"        # PUBLIC: the demo identities only (see 08_protocol_v2.py)
V2 = CKPT / "v2"
CFG = P.Config()
V1_THETA = 0.125
CHECKS = [("registration_valid", "Registration signed by the owner"), ("receipt_valid", "Registry receipt from a trusted registry"),
          ("registered_before_claim", "Registered before the claim"), ("claim_matches_registration", "Claim refers to this registration"),
          ("claim_matches_suspect", "Claim refers to this suspect file"), ("public_signal_count", "Five public signals"),
          ("public_pk_hash", "Proof is for the owner's key"), ("public_config_hash", "Same watermark configuration"),
          ("public_commitment", "Opens the published commitment"), ("public_w_hash", "About this exact model (w_hash)"),
          ("public_nonce", "Made for this claim (nonce)"), ("snark_valid", "Groth16 proof verifies")]

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
args = ap.parse_args()
entry = MC.resolve(args.model)
if entry is None:
    raise SystemExit(f"unknown model {args.model!r}; choose one of: {', '.join(MC.ids())}")
dev = device()
_data = {}


def data():
    if not _data:
        _data.update(load_mnist(dev))
    return _data


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_net(path):
    m = Net().to(dev)
    m.load_state_dict(torch.load(path, map_location=dev, weights_only=True))
    return m.eval()


# ---------------------------------------------------------------- the thief's attacks (as in demos B and F)
def prune(model, ratio):
    m = copy.deepcopy(model)
    with torch.no_grad():
        for mod in m.modules():
            if isinstance(mod, (nn.Conv2d, nn.Linear)):
                w = mod.weight
                w[w.abs() <= w.abs().flatten().kthvalue(int(ratio * w.numel())).values] = 0
    return m


def quantise(model, bits=8):
    m = copy.deepcopy(model)
    with torch.no_grad():
        for p in m.parameters():
            s = p.abs().max() / (2 ** (bits - 1) - 1)
            p.copy_(torch.round(p / s) * s)
    return m


def permute(model):
    m = copy.deepcopy(model)
    perm = torch.randperm(m.conv1.out_channels, generator=torch.Generator().manual_seed(0)).to(dev)
    with torch.no_grad():
        m.conv1.weight.copy_(m.conv1.weight[perm])
        m.conv1.bias.copy_(m.conv1.bias[perm])
        m.conv2.weight.copy_(m.conv2.weight[:, perm])
    return m


def overwrite(model):
    """The thief embeds their own mark (a fixed demo thief identity, so the copy is reproducible)."""
    m = copy.deepcopy(model)
    tseed = int.from_bytes(hashlib.sha256(b"sigil demo thief seed").digest()[:31], "big")
    tpkh = P.pk_hash(hashlib.sha256(b"sigil demo thief key").digest())
    X, b = P.key_matrix(tseed, tpkh, CFG).astype(np.float32), P.signature_bits(tseed, tpkh, CFG)
    finetune_embed(m, (data()["x_att"], data()["y_att"]), X, b, 3, layer=CFG.layer, lam=1.0, device=dev, seed=7)
    return m.eval()


ATTACKS = {"prune65": lambda m: prune(m, 0.65), "prune90": lambda m: prune(m, 0.90), "int8": lambda m: quantise(m, 8),
           "finetune": lambda m: train(copy.deepcopy(m), data()["x_att"], data()["y_att"], 5, seed=7, tag="FTAL-5").eval(),
           "permute": permute, "overwrite": overwrite}

# ---------------------------------------------------------------- 1. the model
banner(f"MODEL TEST: {entry['label']}")
print(f"  group          : {entry['group']}")
print(f"  what it is     : {entry['note']}")
tmp = Path(tempfile.mkdtemp(prefix="sigil_model_"))
net = None
try:
    if entry["derived"]:
        print(f"  making it now  : loading {MC.BUILTIN[MC.SOURCE][1]} and applying the attack…")
        t0 = time.perf_counter()
        torch.manual_seed(7)
        net = ATTACKS[args.model](load_net(MC.ROOT / MC.BUILTIN[MC.SOURCE][2]))
        path = tmp / f"{args.model}.pt"
        torch.save(net.state_dict(), path)
        print(f"                   done in {time.perf_counter() - t0:.1f} s")
    else:
        path = MC.ROOT / entry["file"]
        if path.suffix == ".pt":
            try:
                net = load_net(path)
            except Exception as e:  # noqa: BLE001 - a user's .pt may be another network
                print(f"  (not the demo's network, so no accuracy: {str(e).splitlines()[0][:100]})")
    digest = sha256_file(path)
    print(f"  file           : {entry['file'] or '(made in memory, saved to a temporary file)'}")
    print(f"  sha256         : {digest[:32]}…")

    # ------------------------------------------------------------ 2. accuracy
    acc = accuracy(net, data()["x_test"], data()["y_test"]) if net is not None else None
    print(f"  accuracy       : {acc * 100:.2f}% on 10,000 MNIST test images" if acc is not None else "  accuracy       : n/a")

    # ------------------------------------------------------------ 3. watermark readout
    print("\n  Watermark readout (layer conv2)")
    result = {"model": args.model, "label": entry["label"], "group": entry["group"], "derived": entry["derived"],
              "file": entry["file"], "sha256": digest, "accuracy": acc, "readable": True, "error": None,
              "v2": None, "v1": None, "proof": None, "verdict": None,
              "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    try:
        w = uchida_vector(path, CFG.layer)
        if len(w) != CFG.M:
            raise ValueError(f"layer {CFG.layer} gives {len(w)} values, the watermark needs {CFG.M}")
    except Exception as e:  # noqa: BLE001 - reported, never a crash
        result.update(readable=False, error=str(e).splitlines()[0][:200], verdict="unreadable")
        print(f"  [XX]  can't read the watermarked layer: {result['error']}")
        print("\n  VERDICT: CAN'T TEST: this model has no layer the watermark could be in")
    else:
        owner = KeyPair.load(V2 / "owner.key", DEMO_PASS)
        seed = int(secretbox.load(V2 / "seed.json", DEMO_PASS, "seed")["seed"])
        pkh = P.pk_hash(owner.public_bytes)
        det = P.detect(seed, pkh, CFG, w)
        result["v2"] = {"errors": det.errors, "ber": det.errors / CFG.T, "max_err": CFG.max_err, "accepted": det.accepted}
        print(f"  {'[ok]' if det.accepted else '[XX]'}  protocol v2 owner ({owner.public_hex[:12]}…): "
              f"{det.errors}/{CFG.T} bits wrong (accept at ≤ {CFG.max_err})")
        secret = json.loads((CKPT / "owner_secret.json").read_text())
        s1 = bytes.fromhex(secret["seed_hex"])
        bits = (derive_key(s1) @ w.astype(np.float32) >= 0).astype(np.uint8)
        ber1 = float((bits != derive_signature(s1, secret["owner_id"])).mean())
        result["v1"] = {"ber": ber1, "accepted": ber1 <= V1_THETA}
        print(f"  {'[ok]' if ber1 <= V1_THETA else '[--]'}  protocol v1 owner ({secret['owner_id']}): "
              f"BER {ber1:.3f} (accept at ≤ {V1_THETA})")

        # -------------------------------------------------------- 4. zero-knowledge proof of ownership
        print("\n  Proof of ownership (protocol v2: Circom + Groth16)")
        if not det.accepted:
            reason = f"no proof possible: {det.errors}/{CFG.T} bits wrong (> {CFG.max_err})"
            result["proof"] = {"made": False, "accepted": False, "checks": {}, "reasons": [reason], "timing": None,
                               "proof_bytes": None, "nonce": None}
            result["verdict"] = "no_proof"
            print(f"  {reason}: the circuit has no valid witness, so no proof is attempted")
            print("\n  VERDICT: NOT PROVEN: the owner's watermark isn't in this model")
        else:
            art = Z.artifacts(CFG)
            if not art.zkey.exists():
                raise SystemExit(f"circuit not set up: run `sigil zk-setup` (needs {art.zkey.name})")
            reg = json.loads((V2 / "registration.json").read_text())
            rcp = json.loads((V2 / "receipt.json").read_text())
            trusted = {KeyPair.load(V2 / "registry.key", DEMO_PASS).public_hex}
            time.sleep(0.01)                     # the claim is opened strictly after the receipt
            claim = make_claim(reg, digest)
            print(f"  claim opened   : nonce {claim['nonce'][:10]}…{claim['nonce'][-6:]} for this file")
            proof, public, timing = Z.prove(CFG, P.circuit_input(seed, P.quantize(w, CFG), pkh, CFG, int(claim["nonce"])))[:3]
            size = len(json.dumps(proof, indent=2))       # as proof.json is saved (demo F: 879 B)
            print(f"  proof made     : witness {timing['witness_s']:.2f} s, prove {timing['prove_s']:.2f} s, {size} bytes")
            v = verify_ownership(proof=proof, public=public, registration=reg, receipt=rcp, claim=claim, suspect_w=w,
                                 suspect_model_sha256=digest, trusted_registry_keys=trusted).to_dict()
            print()
            for key, label in CHECKS:
                if key in v["checks"]:
                    print(f"  {'[ok]' if v['checks'][key] else '[XX]'}  {label}")
            result["proof"] = {"made": True, "accepted": v["accepted"], "checks": v["checks"], "reasons": v["reasons"],
                               "timing": timing, "proof_bytes": size, "nonce": claim["nonce"]}
            result["verdict"] = "proven" if v["accepted"] else "rejected"
            print("\n  VERDICT: " + ("OWNERSHIP PROVEN: 0 watermark bits revealed" if v["accepted"]
                                     else "REJECTED: " + "; ".join(v["reasons"])))
    write_json(f"model_tests/{MC.safe_name(args.model)}.json", result)
    print(f"\n  Saved results/model_tests/{MC.safe_name(args.model)}.json")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
