"""End-to-end zero-knowledge tests: Groth16 proofs from circuits/ownership.circom (ZK-01..ZK-07).

Needs circom, node, circuits/node_modules and a completed setup for the demo config:
    python -c "from sigil import protocol as P; from sigil.zk.circom import setup; setup(P.Config())"
Skipped automatically when the setup is missing.
"""
import copy
import hashlib

import numpy as np
import pytest

from sigil import protocol as P
from sigil.identity import KeyPair
from sigil.records import make_claim, make_receipt, make_registration
from sigil.verify import verify_ownership

pytestmark = [pytest.mark.zk, pytest.mark.slow]
CFG = P.Config()

try:
    from sigil.zk import circom as Z
    _a = Z.artifacts(CFG)
    READY = _a.zkey.exists() and _a.wasm.exists() and _a.vkey.exists()
except Exception:  # toolchain missing
    READY = False
if not READY:
    pytest.skip("zk setup for the demo config not found (run sigil.zk.circom.setup)", allow_module_level=True)


def embed_like(seed, pkh, flips=0, scale=0.02):
    X = P.key_matrix(seed, pkh, CFG).astype(float)
    target = P.signature_bits(seed, pkh, CFG).astype(float) * 2 - 1
    target[:flips] *= -1
    w = X.T @ target / CFG.M * scale
    for _ in range(200):
        bad = np.sign(X @ P.quantize(w, CFG)) != target
        if not bad.any():
            return w
        w += 0.5 * scale * (X[bad].T @ target[bad]) / CFG.M
    raise AssertionError("could not construct the vector")


@pytest.fixture(scope="module")
def world():
    registry, owner = KeyPair.generate(), KeyPair.generate()
    seed = P.new_seed()
    pkh = P.pk_hash(owner.public_bytes)
    w = embed_like(seed, pkh)
    model_sha = hashlib.sha256(np.asarray(w).tobytes()).hexdigest()
    reg = make_registration(owner, seed, CFG, model_sha, created_at="2026-10-01T09:00:00Z")
    rcp = make_receipt(registry, reg, registered_at="2026-10-01T09:00:01Z")
    claim = make_claim(reg, model_sha)
    proof, public, timing = Z.prove(CFG, P.circuit_input(seed, P.quantize(w, CFG), pkh, CFG, int(claim["nonce"])))
    return dict(registry=registry, owner=owner, seed=seed, pkh=pkh, w=w, model_sha=model_sha, reg=reg, rcp=rcp,
                claim=claim, proof=proof, public=public, timing=timing)


def check(world, **over):
    args = dict(proof=world["proof"], public=world["public"], registration=world["reg"], receipt=world["rcp"],
                claim=world["claim"], suspect_w=world["w"], suspect_model_sha256=world["model_sha"],
                trusted_registry_keys={world["registry"].public_hex})
    args.update(over)
    return verify_ownership(**args)


def test_owner_proof_accepted(world):
    v = check(world)
    assert v.accepted, v.reasons
    assert world["public"] == [world["reg"]["pk_hash"], world["reg"]["config_hash"], world["reg"]["commitment"],
                               str(P.w_hash(P.quantize(world["w"], CFG), CFG)), world["claim"]["nonce"]]


def test_threshold_boundary_in_circuit(world):
    for flips, ok in ((8, True), (9, False)):
        w = embed_like(world["seed"], world["pkh"], flips=flips)
        inp = P.circuit_input(world["seed"], P.quantize(w, CFG), world["pkh"], CFG, 1)
        if ok:
            Z.prove(CFG, inp)
        else:
            with pytest.raises(Z.ZkError):
                Z.prove(CFG, inp)


def test_thief_cannot_prove_stolen_model(world):
    """Demo C's forgery in v2: the thief holds the weights but not the seed. With their own seed and key,
    the derived signature doesn't match; with the owner's commitment, the opening fails."""
    thief = KeyPair.generate()
    tseed, tpkh = P.new_seed(), P.pk_hash(thief.public_bytes)
    wq = P.quantize(world["w"], CFG)
    assert not P.detect(tseed, tpkh, CFG, wq).accepted
    with pytest.raises(Z.ZkError):
        Z.prove(CFG, P.circuit_input(tseed, wq, tpkh, CFG, 1))
    forged = P.circuit_input(tseed, wq, world["pkh"], CFG, 1)
    forged["commitment"] = world["reg"]["commitment"]
    with pytest.raises(Z.ZkError):
        Z.prove(CFG, forged)


def test_free_signature_attack_impossible(world):
    """D1 attack: choose b := extract(X_thief, stolen). In v2 the circuit derives b from the seed itself."""
    thief = KeyPair.generate()
    tseed, tpkh = P.new_seed(), P.pk_hash(thief.public_bytes)
    wq = P.quantize(world["w"], CFG)
    fitted = P.extract_bits(P.key_matrix(tseed, tpkh, CFG), wq)       # BER 0 against the thief's own X ...
    assert P.errors(fitted, P.signature_bits(tseed, tpkh, CFG)) > CFG.max_err   # ... but not the derived b
    with pytest.raises(Z.ZkError):
        Z.prove(CFG, P.circuit_input(tseed, wq, tpkh, CFG, 1))


def test_proof_for_a_different_model_rejected(world):
    other = np.asarray(world["w"]) * 1.0
    other[0] += 0.01
    v = check(world, suspect_w=other)
    assert not v.accepted and any("different model" in r for r in v.reasons)


def test_replay_with_another_claim_rejected(world):
    v = check(world, claim=make_claim(world["reg"], world["model_sha"]))
    assert not v.accepted and any("nonce" in r for r in v.reasons)


def test_tampered_proof_rejected(world):
    bad = copy.deepcopy(world["proof"])
    bad["pi_a"][0] = str((int(bad["pi_a"][0]) + 1))
    v = check(world, proof=bad)
    assert not v.accepted and "the zk-SNARK does not verify" in v.reasons


def test_tampered_public_signal_rejected(world):
    pub = list(world["public"])
    pub[2] = str(int(pub[2]) ^ 1)
    v = check(world, public=pub)
    assert not v.accepted and not v.checks["snark_valid"]


def test_unregistered_or_untrusted_registry_rejected(world):
    rogue = KeyPair.generate()
    v = check(world, receipt=make_receipt(rogue, world["reg"]))
    assert not v.accepted and any("trusted registry" in r for r in v.reasons)


def test_claim_before_registration_rejected(world):
    early = dict(world["claim"], opened_at="2026-09-01T00:00:00Z")
    v = check(world, claim=early)
    assert not v.accepted and any("earlier than the claim" in r for r in v.reasons)
