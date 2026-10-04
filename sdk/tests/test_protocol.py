"""Protocol v2 (CR-06, WM-08): derivations, binding, quantisation and detection."""
import hashlib

import numpy as np
import pytest

from sigil import protocol as P

CFG = P.Config()
PK = hashlib.sha256(b"test-owner").digest()
PKH = P.pk_hash(PK)
SEED = int.from_bytes(hashlib.sha256(b"test-seed").digest(), "big") >> 8


def embed_like(seed=SEED, pkh=PKH, cfg=CFG, flips=0, scale=0.02):
    """A float vector whose quantised projections match the signature except for `flips` bits."""
    X = P.key_matrix(seed, pkh, cfg).astype(float)
    target = P.signature_bits(seed, pkh, cfg).astype(float) * 2 - 1
    target[:flips] *= -1
    w = X.T @ target / cfg.M * scale
    for _ in range(200):
        bad = np.sign(X @ P.quantize(w, cfg)) != target
        if not bad.any():
            return w
        w += 0.5 * scale * (X[bad].T @ target[bad]) / cfg.M
    raise AssertionError("could not construct the vector")


def test_key_is_pm1_and_deterministic():
    X = P.key_matrix(SEED, PKH, CFG)
    assert X.shape == (CFG.T, CFG.M) and X.dtype == np.int8
    assert set(np.unique(X)) == {-1, 1}
    assert np.array_equal(X, P.key_matrix(SEED, PKH, CFG))
    assert abs(X.mean()) < 0.03            # balanced


def test_key_and_signature_depend_on_owner_key():
    other = P.pk_hash(hashlib.sha256(b"someone-else").digest())
    assert not np.array_equal(P.key_matrix(SEED, PKH, CFG), P.key_matrix(SEED, other, CFG))
    assert not np.array_equal(P.signature_bits(SEED, PKH, CFG), P.signature_bits(SEED, other, CFG))


def test_commitment_binds_config():
    assert P.commitment(SEED, PKH, CFG) != P.commitment(SEED, PKH, P.Config(max_err=9))
    assert P.commitment(SEED, PKH, CFG) != P.commitment(SEED, PKH, P.Config(layer="conv1"))
    assert P.config_hash(CFG) == P.config_hash(P.Config.from_dict(CFG.to_dict()))


def test_seed_range_enforced():
    with pytest.raises(ValueError):
        P.commitment(1 << 248, PKH, CFG)
    assert 0 <= P.new_seed() < 1 << 248


def test_quantize_bounds_and_rounding():
    w = np.zeros(CFG.M)
    w[0], w[1] = 0.5 / 2**16, -1.5 / 2**16           # round half to even
    q = P.quantize(w, CFG)
    assert q[0] == 0 and q[1] == -2
    with pytest.raises(ValueError):
        P.quantize(np.full(CFG.M, 2.0**(CFG.w_bits - CFG.scale_bits)), CFG)
    with pytest.raises(ValueError):
        P.quantize(np.full(CFG.M, np.nan), CFG)


def test_uchida_vector_is_framework_independent():
    rng = np.random.default_rng(0)
    oihw = rng.normal(size=(64, 32, 3, 3)).astype(np.float32)
    hwio = np.transpose(oihw, (2, 3, 1, 0))
    assert np.array_equal(P.uchida_vector(oihw, "OIHW"), P.uchida_vector(hwio, "HWIO"))
    oi = rng.normal(size=(10, 128)).astype(np.float32)
    assert np.array_equal(P.uchida_vector(oi, "OI"), P.uchida_vector(oi.T, "IO"))
    assert P.uchida_vector(oihw, "OIHW").shape == (288,)
    with pytest.raises(ValueError):
        P.uchida_vector(oi, "OIHW")


def test_w_hash_binds_every_value():
    q = P.quantize(embed_like(), CFG)
    h = P.w_hash(q, CFG)
    for j in (0, 14, 15, 287):
        q2 = q.copy()
        q2[j] += 1
        assert P.w_hash(q2, CFG) != h


@pytest.mark.parametrize("flips,accepted", [(0, True), (8, True), (9, False)])
def test_detection_threshold(flips, accepted):
    d = P.detect(SEED, PKH, CFG, embed_like(flips=flips))
    assert d.errors == flips and d.accepted is accepted


def test_random_and_wrong_key_rejected():
    rng = np.random.default_rng(3)
    assert not P.detect(SEED, PKH, CFG, rng.normal(0, 0.02, CFG.M)).accepted
    other = P.pk_hash(hashlib.sha256(b"thief").digest())
    assert not P.detect(SEED, other, CFG, embed_like()).accepted


def test_circuit_input_shapes():
    q = P.quantize(embed_like(), CFG)
    inp = P.circuit_input(SEED, q, PKH, CFG, nonce=7)
    assert len(inp["w"]) == CFG.M and all(isinstance(v, str) for v in inp["w"])
    assert set(P.PUBLIC_SIGNALS) <= set(inp)
