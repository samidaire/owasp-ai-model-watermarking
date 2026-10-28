"""Unit tests for sigil.triggerset (WM-06): derivation, commitment, statistics, verification."""
import numpy as np
import pytest

from sigil import triggerset as TS

SPEC = TS.Spec(n=50, shape=(1, 28, 28), num_classes=10, grid=7)


def test_derivation_is_deterministic_and_bound_to_seed_and_owner():
    a = TS.derive(1, 2, SPEC)
    b = TS.derive(1, 2, SPEC)
    assert np.array_equal(a.images, b.images) and np.array_equal(a.labels, b.labels)
    assert a.commitment() == b.commitment()
    assert a.commitment() != TS.derive(3, 2, SPEC).commitment()      # other seed
    assert a.commitment() != TS.derive(1, 4, SPEC).commitment()      # other owner key


def test_shapes_and_ranges():
    ts = TS.derive(7, 8, TS.Spec(n=20, shape=(3, 32, 32), num_classes=10, grid=8))
    assert ts.images.shape == (20, 3, 32, 32) and ts.images.dtype == np.uint8
    assert ts.labels.shape == (20,) and ts.labels.dtype == np.uint8
    assert ts.labels.max() < 10
    assert ts.images.std() > 30          # not a constant image


def test_labels_are_roughly_uniform():
    ts = TS.derive(11, 12, TS.Spec(n=5000, shape=(1, 7, 7), grid=7))
    counts = np.bincount(ts.labels, minlength=10)
    chi2 = ((counts - 500) ** 2 / 500).sum()
    assert chi2 < 40          # df = 9; P[chi2 > 40] < 1e-5 under uniformity


def test_commitment_detects_any_change():
    ts = TS.derive(1, 2, SPEC)
    c = ts.commitment()
    assert TS.verify_commitment(ts, c) and TS.verify_commitment(ts, c.upper())
    img = ts.images.copy()
    img[3, 0, 5, 5] ^= 1
    assert not TS.verify_commitment(TS.TriggerSet(img, ts.labels, 10), c)
    lab = ts.labels.copy()
    lab[0] = (lab[0] + 1) % 10
    assert not TS.verify_commitment(TS.TriggerSet(ts.images, lab, 10), c)
    assert not TS.verify_commitment(TS.TriggerSet(ts.images, ts.labels, 11), c)   # header is committed


def test_known_answer_vector():
    """Pins the v1 derivation so another implementation (or a refactor) can check itself."""
    ts = TS.derive(1, 2, TS.Spec(n=4, shape=(1, 8, 8), num_classes=10, grid=4))
    assert ts.labels.tolist() == KAT_LABELS
    assert ts.commitment() == KAT_COMMITMENT


def test_spec_validation():
    with pytest.raises(ValueError):
        TS.Spec(shape=(1, 28, 28), grid=8)
    with pytest.raises(ValueError):
        TS.Spec(n=0)
    with pytest.raises(ValueError):
        TS.derive(-1, 2, SPEC)


def test_threshold_and_binomial_tail():
    assert TS.threshold(100, 10, 1e-6) == 28
    assert TS.binom_sf(28, 100, 0.1) <= 1e-6 < TS.binom_sf(27, 100, 0.1)
    assert TS.binom_sf(0, 10, 0.3) == 1.0
    assert abs(TS.binom_sf(1, 1, 0.25) - 0.25) < 1e-12


def test_score_and_verify():
    ts = TS.derive(1, 2, SPEC)
    perfect = TS.score(ts.labels, ts)
    assert perfect.accepted and perfect.matches == 50 and perfect.p_value < 1e-40
    const = TS.score(np.zeros(50, dtype=int), ts)
    assert not const.accepted and const.matches == int((ts.labels == 0).sum())
    with pytest.raises(ValueError):
        TS.score(np.zeros(3), ts)
    seen = {}

    def api(x):
        seen["x"] = x
        return ts.labels
    r = TS.verify(api, ts, mean=[0.5], std=[0.25])
    assert r.accepted
    assert seen["x"].dtype == np.float32 and seen["x"].shape == (50, 1, 28, 28)
    assert np.allclose(seen["x"], (ts.images / 255.0 - 0.5) / 0.25, atol=1e-6)


def test_torch_sampler_and_predictor():
    torch = pytest.importorskip("torch")
    ts = TS.derive(1, 2, SPEC)
    extra = TS.sampler(ts, [0.1307], [0.3081], per_batch=8)
    x, y = extra(torch.Generator().manual_seed(0))
    assert x.shape == (8, 1, 28, 28) and y.dtype == torch.int64
    model = torch.nn.Sequential(torch.nn.Flatten(), torch.nn.Linear(784, 10))
    pred = TS.torch_predictor(model)(ts.normalized([0.1307], [0.3081]))
    assert pred.shape == (50,)


KAT_LABELS = [1, 7, 0, 0]
KAT_COMMITMENT = "90d3eb8d9e786e79068b85a86989ab24ff996c682ae402c670e8c1506b876ba4"
