"""Unit tests for sigil.attacks (ROB-01, ROB-02, ROB-03): fast, CPU, tiny models.

The one test that trains on MNIST is marked ``ml``.
"""
import numpy as np
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from sigil import attacks as A
from sigil import protocol as P


class Tiny(nn.Module):
    """8x8 single-channel input -> conv1 (4) -> [bn1] -> conv2 (6) -> fc (10)."""

    def __init__(self, bn: bool = False):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 4, 3)
        self.bn1 = nn.BatchNorm2d(4) if bn else nn.Identity()
        self.conv2 = nn.Conv2d(4, 6, 3)
        self.fc = nn.Linear(6 * 4 * 4, 10)

    def forward(self, x):
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.conv2(x))
        return self.fc(x.flatten(1))


def tiny(seed=0, bn=False):
    torch.manual_seed(seed)
    m = Tiny(bn)
    if bn:   # non-trivial running stats so BN permutation matters
        with torch.no_grad():
            m.bn1.running_mean.uniform_(-1, 1)
            m.bn1.running_var.uniform_(0.5, 2)
            m.bn1.weight.uniform_(0.5, 1.5)
            m.bn1.bias.uniform_(-0.5, 0.5)
    return m.eval()


def data(n=64, seed=1):
    g = torch.Generator().manual_seed(seed)
    return torch.randn(n, 1, 8, 8, generator=g), torch.randint(0, 10, (n,), generator=g)


def state(m):
    return {k: v.detach().clone() for k, v in m.state_dict().items()}


def same_state(a, b):
    return all(torch.equal(a[k], b[k]) for k in a)


QUICK = A.Fit(epochs=2, lr=1e-2, batch_size=16, seed=3)


# ------------------------------------------------------------------ purity: no attack changes its input
@pytest.mark.parametrize("attack", [
    lambda m, x, y: A.prune_magnitude(m, 0.5),
    lambda m, x, y: A.prune_channels(m, 0.5),
    lambda m, x, y: A.prune_finetune(m, 0.5, x, y, QUICK),
    lambda m, x, y: A.fine_prune(m, "conv2", 0.5, x, y, QUICK),
    lambda m, x, y: A.quantize_weights(m, 4),
    lambda m, x, y: A.ptq(m, 8, x),
    lambda m, x, y: A.ftll(m, x, y, QUICK),
    lambda m, x, y: A.ftal(m, x, y, QUICK),
    lambda m, x, y: A.rtll(m, x, y, QUICK),
    lambda m, x, y: A.rtal(m, x, y, QUICK),
    lambda m, x, y: A.overwrite(m, x, y, QUICK, layer="conv2", X=np.ones((4, 36)), b=np.ones(4)),
    lambda m, x, y: A.permute_channels(m, "conv1", "conv2", seed=1),
    lambda m, x, y: A.kmeans_share(m, 4),
    lambda m, x, y: A.low_rank(m, 0.25, include_conv=True),
    lambda m, x, y: A.distill(m, tiny(9, bn=True), x, QUICK),
    lambda m, x, y: A.extract(m, tiny(9, bn=True), x, 32, QUICK)[0],
])
def test_attacks_return_a_copy_and_keep_shapes(attack):
    m = tiny(bn=True)
    x, y = data()
    before = state(m)
    out = attack(m, x, y)
    assert out is not m
    assert same_state(before, state(m)), "the input model was modified"
    assert {k: v.shape for k, v in out.state_dict().items()} == {k: v.shape for k, v in before.items()}
    assert out(x).shape == (x.shape[0], 10)


# ------------------------------------------------------------------ pruning
def test_prune_magnitude_exact_fraction_per_layer():
    m = A.prune_magnitude(tiny(), 0.3)
    for _, mod in A.weight_layers(m):
        n = mod.weight.numel()
        assert int((mod.weight == 0).sum()) == round(0.3 * n)
    assert torch.equal(A.prune_magnitude(tiny(), 0.0).conv2.weight, tiny().conv2.weight)


def test_prune_magnitude_removes_smallest():
    src = tiny()
    m = A.prune_magnitude(src, 0.5, layers=["fc"])
    kept = src.fc.weight.abs()[m.fc.weight != 0]
    dropped = src.fc.weight.abs()[m.fc.weight == 0]
    assert kept.min() >= dropped.max()
    assert torch.equal(m.conv1.weight, src.conv1.weight)


def test_prune_channels_zeroes_whole_filters_and_bn():
    m = A.prune_channels(tiny(bn=True), 0.5)
    zero_filters = (m.conv1.weight.flatten(1).abs().sum(1) == 0)
    assert int(zero_filters.sum()) == 2
    assert torch.all(m.bn1.weight[zero_filters] == 0) and torch.all(m.bn1.bias[zero_filters] == 0)
    assert int((m.conv2.weight.flatten(1).abs().sum(1) == 0).sum()) == 3
    assert not torch.any(m.fc.weight == 0)            # the classifier is never channel-pruned


def test_prune_finetune_keeps_mask():
    x, y = data()
    m = A.prune_finetune(tiny(), 0.6, x, y, QUICK)
    for _, mod in A.weight_layers(m):
        assert int((mod.weight == 0).sum()) >= round(0.6 * mod.weight.numel())


def test_fine_prune_keeps_pruned_channels_zero():
    x, y = data()
    m = A.fine_prune(tiny(bn=True), "conv1", 0.5, x, y, QUICK)
    dead = m.conv1.weight.flatten(1).abs().sum(1) == 0
    assert int(dead.sum()) == 2
    assert torch.all(m.conv1.bias[dead] == 0) and torch.all(m.bn1.weight[dead] == 0)


def test_paired_norm():
    m = tiny(bn=True)
    assert A.paired_norm(m, "conv1") == "bn1"
    assert A.paired_norm(m, "conv2") is None


# ------------------------------------------------------------------ quantisation
@pytest.mark.parametrize("bits", [8, 4])
def test_per_channel_quantisation_matches_torch_ao_observer(bits):
    from torch.ao.quantization.observer import MinMaxObserver, PerChannelMinMaxObserver

    m = tiny()
    w = m.conv2.weight.detach()
    qmin, qmax = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    obs = PerChannelMinMaxObserver(ch_axis=0, dtype=torch.qint8, qscheme=torch.per_channel_symmetric,
                                   quant_min=qmin, quant_max=qmax)
    obs(w)
    scale, zp = obs.calculate_qparams()
    ref = torch.fake_quantize_per_channel_affine(w, scale.float(), zp.int(), 0, qmin, qmax)
    q = A.quantize_weights(m, bits, "channel")
    assert torch.equal(q.conv2.weight, ref)
    # every channel uses at most 2**bits distinct levels, all multiples of its scale
    for o in range(w.shape[0]):
        levels = q.conv2.weight[o] / scale[o]
        assert torch.allclose(levels, levels.round(), atol=1e-4)
        assert levels.round().unique().numel() <= 1 << bits
    obs_t = MinMaxObserver(dtype=torch.qint8, qscheme=torch.per_tensor_symmetric, quant_min=qmin, quant_max=qmax)
    obs_t(w)
    s_t, _ = obs_t.calculate_qparams()
    ref_t = torch.fake_quantize_per_tensor_affine(w, float(s_t), 0, qmin, qmax)
    assert torch.equal(A.quantize_weights(m, bits, "tensor").conv2.weight, ref_t)


def test_quantisation_keeps_bias_float_by_default():
    m = tiny()
    assert torch.equal(A.quantize_weights(m, 4).conv1.bias, m.conv1.bias)
    assert not torch.equal(A.quantize_weights(m, 4, "tensor", include_bias=True).conv1.bias, m.conv1.bias)


def test_activation_quantisation_is_close_at_8_bits():
    m = tiny()
    x, _ = data()
    q = A.quantize_activations(m, x, 8)
    assert torch.equal(q.conv1.weight, m.conv1.weight)
    assert (q(x) - m(x)).abs().max() < 0.1 * m(x).abs().max()


# ------------------------------------------------------------------ fine-tuning family
def test_training_attacks_are_deterministic_and_seed_dependent():
    x, y = data()
    for attack in (A.ftal, A.rtal, A.rtll):
        a = state(attack(tiny(), x, y, QUICK))
        b = state(attack(tiny(), x, y, QUICK))
        c = state(attack(tiny(), x, y, QUICK.with_(seed=4)))
        assert same_state(a, b)
        assert not same_state(a, c)


def test_ftll_and_rtll_touch_only_the_last_layer():
    x, y = data()
    src = tiny(bn=True)
    for attack in (A.ftll, A.rtll):
        m = attack(src, x, y, QUICK)
        for k, v in state(src).items():
            if not k.startswith("fc."):
                assert torch.equal(v, m.state_dict()[k]), k   # incl. BN running stats (frozen in eval mode)
        assert not torch.equal(m.fc.weight, src.fc.weight)


def test_rtal_reinitialises_classifier():
    x, y = data()
    src = tiny()
    m = A.rtal(src, x, y, QUICK.with_(epochs=0))
    assert not torch.equal(m.fc.weight, src.fc.weight)
    assert torch.equal(m.conv1.weight, src.conv1.weight)


def test_uchida_vector_matches_protocol():
    m = tiny()
    w = m.conv2.weight.detach()
    assert np.allclose(A.uchida_vector(w).double().numpy(), P.uchida_vector(w.numpy(), "OIHW"))


def test_overwrite_embeds_the_thiefs_mark():
    x, y = data(128)
    rng = np.random.default_rng(0)
    X = rng.choice([-1.0, 1.0], size=(8, 36))
    b = rng.integers(0, 2, 8)
    m = A.overwrite(tiny(), x, y, A.Fit(epochs=20, lr=1e-2, batch_size=32, seed=0), layer="conv2", X=X, b=b, lam=5.0)
    bits = (X @ A.uchida_vector(m.conv2.weight).detach().double().numpy() >= 0).astype(int)
    assert (bits == b).all()


# ------------------------------------------------------------------ permutation and realignment
@pytest.mark.parametrize("bn", [False, True])
def test_permutation_is_functionally_identical(bn):
    m = tiny(bn=bn)
    x, _ = data()
    p = A.permute_channels(m, "conv1", "conv2", seed=5)
    assert torch.allclose(p(x), m(x), atol=1e-5)
    assert not torch.equal(p.conv2.weight, m.conv2.weight)
    w0, w1 = A.uchida_vector(m.conv2.weight).view(4, 9), A.uchida_vector(p.conv2.weight).view(4, 9)
    perm = torch.randperm(4, generator=torch.Generator().manual_seed(5))
    assert torch.allclose(w1, w0[perm])


def test_permutation_rejects_non_permutation():
    with pytest.raises(ValueError):
        A.permute_channels(tiny(), "conv1", "conv2", perm=[0, 0, 1, 2])


@pytest.mark.parametrize("bn", [False, True])
def test_realign_undoes_permutation_without_knowing_it(bn):
    owner = tiny(bn=bn)
    stolen = A.permute_channels(owner, "conv1", "conv2", seed=11)
    # the thief also perturbs every weight (as fine-tuning would); the owner only has their own copy
    with torch.no_grad():
        for p in stolen.parameters():
            p.add_(0.05 * p.abs().mean() * torch.randn_like(p))
    back, perm, info = A.realign(stolen, owner, "conv1", "conv2")
    assert sorted(perm) == list(range(4))
    expected = torch.argsort(torch.randperm(4, generator=torch.Generator().manual_seed(11))).tolist()
    assert perm == expected
    assert torch.allclose(back.conv1.weight, owner.conv1.weight, atol=0.2)
    assert info["mean_similarity"] > 0.9
    _, perm_id, info_id = A.realign(owner, owner, "conv1", "conv2")
    assert info_id["identity"] and perm_id == [0, 1, 2, 3]


# ------------------------------------------------------------------ compression
def test_kmeans_share_limits_distinct_values_and_is_deterministic():
    a = A.kmeans_share(tiny(), 4, seed=2)
    b = A.kmeans_share(tiny(), 4, seed=2)
    for (_, ma), (_, mb) in zip(A.weight_layers(a), A.weight_layers(b)):
        assert ma.weight.unique().numel() <= 4
        assert torch.equal(ma.weight, mb.weight)


def test_low_rank():
    src = tiny()
    m = A.low_rank(src, 0.25)
    assert torch.linalg.matrix_rank(m.fc.weight.detach()) <= 3
    assert torch.equal(m.conv2.weight, src.conv2.weight)          # linear only by default
    mc = A.low_rank(src, 0.5, include_conv=True)
    assert torch.linalg.matrix_rank(mc.conv2.weight.detach().flatten(1)) <= 3
    full = A.low_rank(src, 1.0)
    assert torch.allclose(full.fc.weight, src.fc.weight, atol=1e-5)


# ------------------------------------------------------------------ distillation and extraction
def test_build_queries_cycles_pool_with_augmentation():
    x, _ = data(10)
    with pytest.raises(ValueError):
        A.build_queries(x, 25)
    flip = lambda xb, g: xb.flip(3)  # noqa: E731
    q = A.build_queries(x, 25, seed=1, augment=flip)
    assert q.shape[0] == 25
    assert torch.equal(q, A.build_queries(x, 25, seed=1, augment=flip))
    assert torch.equal(q[10:20], q[:10].flip(3))


def test_extract_uses_only_the_budget_and_learns_the_victim():
    x, _ = data(256)
    victim = tiny(0)
    student, info = A.extract(victim, tiny(5), x, 200, A.Fit(epochs=30, lr=1e-2, batch_size=32, seed=0),
                              output="labels")
    assert info["queries"] == 200
    assert info["agreement"] > 0.5
    s2, _ = A.extract(victim, tiny(5), x, 200, A.Fit(epochs=30, lr=1e-2, batch_size=32, seed=0), output="labels")
    assert same_state(state(student), state(s2))


def test_distill_moves_student_towards_teacher():
    x, _ = data(256)
    teacher, student = tiny(0), tiny(7)
    before = (A.predict(student, x).argmax(1) == A.predict(teacher, x).argmax(1)).float().mean()
    s = A.distill(teacher, student, x, A.Fit(epochs=30, lr=1e-2, batch_size=32, seed=0))
    after = (A.predict(s, x).argmax(1) == A.predict(teacher, x).argmax(1)).float().mean()
    assert after > before


# ------------------------------------------------------------------ one real-model check
@pytest.mark.ml
@pytest.mark.slow
def test_mnist_v2_mark_embeds_and_survives_int8():
    """Embeds a protocol-v2 key in the demo MNIST CNN (1 epoch) and checks per-channel int8 keeps it."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "demo"))
    from wm_core import Net, load_mnist  # noqa: E402

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    d = load_mnist(dev)
    cfg = P.Config()
    seed, pkh = 12345, 678
    X, b = P.key_matrix(seed, pkh, cfg).astype(np.float32), P.signature_bits(seed, pkh, cfg)
    torch.manual_seed(0)
    m = A.fit(Net().to(dev), d["x_owner"][:20000], d["y_owner"][:20000], A.Fit(epochs=1, seed=0),
              regularizer=A.uchida_regularizer("conv2", X, b, 1.0))
    vec = lambda mm: A.uchida_vector(mm.conv2.weight).detach().double().cpu().numpy()  # noqa: E731
    assert P.detect(seed, pkh, cfg, vec(m)).errors == 0
    assert P.detect(seed, pkh, cfg, vec(A.quantize_weights(m, 8))).accepted
    assert A.accuracy(m, d["x_test"], d["y_test"]) > 0.95
