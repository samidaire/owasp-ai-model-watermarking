"""PyTorch adapter (WM-01, WM-03), PyTorch -> ONNX (WM-05) and safe torch loading (SDK-04).

Watermarks the demo MNIST CNN (demo/wm_core.Net) at conv2 with a protocol-v2 key (T=64, M=288).
"""
import hashlib
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
import torch.nn as nn  # noqa: E402

from sigil import adapters  # noqa: E402
from sigil import protocol as P  # noqa: E402
from sigil.adapters.torch_adapter import TorchWatermark, finetune_embed, uchida_tensor  # noqa: E402
from sigil.embed import embed_torch, watermark_key  # noqa: E402

pytestmark = pytest.mark.ml

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "demo" / "data" / "train-images-idx3-ubyte.gz").exists():
    pytest.skip("MNIST not found in demo/data", allow_module_level=True)
sys.path.insert(0, str(ROOT / "demo"))
import wm_core  # noqa: E402

CFG = P.Config(T=64, M=288, layer="conv2", max_err=8)
PK = hashlib.sha256(b"m4-torch-owner").digest()
PKH = P.pk_hash(PK)
SEED = int.from_bytes(hashlib.sha256(b"m4-torch-seed").digest(), "big") >> 8
N_TRAIN, EPOCHS = 20000, 2
TIMINGS = {}


def _accuracy(model, x, y):
    return wm_core.accuracy(model, x, y)


@pytest.fixture(scope="module")
def mnist():
    dev = wm_core.device()
    d = wm_core.load_mnist(dev)
    return dev, d["x_owner"][:N_TRAIN], d["y_owner"][:N_TRAIN], d["x_test"], d["y_test"]


@pytest.fixture(scope="module")
def models(mnist):
    """(clean, watermarked, detection): same init, same data order; only the regulariser differs."""
    dev, x, y, xt, yt = mnist
    torch.manual_seed(0)
    clean = wm_core.Net().to(dev)
    t = time.time()
    wm_core.train(clean, x, y, EPOCHS, seed=0, tag="clean")             # the demo's recipe, no watermark
    TIMINGS["clean_train_s"] = time.time() - t
    torch.manual_seed(0)
    wm = wm_core.Net().to(dev)
    t = time.time()
    wm, det = embed_torch(wm, (x, y), CFG, SEED, PKH, epochs=EPOCHS, lam=1.0, train_seed=0)
    TIMINGS["wm_train_s"] = time.time() - t
    acc_clean, acc_wm = _accuracy(clean, xt, yt), _accuracy(wm, xt, yt)
    print(f"\n[torch {dev}] clean acc={acc_clean:.4f} wm acc={acc_wm:.4f} cost={100 * (acc_clean - acc_wm):.2f}pp "
          f"errors={det.errors}/{CFG.T} clean-model errors={adapters.detect(clean, SEED, PKH, CFG).errors} "
          f"train {TIMINGS['wm_train_s']:.1f}s")
    return clean, wm, det, acc_clean, acc_wm


# ------------------------------------------------------------------ embedding and detection
def test_watermark_accepted_with_small_accuracy_cost(models):
    clean, wm, det, acc_clean, acc_wm = models
    assert det.accepted and det.errors <= CFG.max_err
    assert det == adapters.detect(wm, SEED, PKH, CFG)
    assert acc_wm > 0.95
    assert acc_clean - acc_wm < 0.01                       # under 1 percentage point


def test_clean_model_and_wrong_owner_rejected(models):
    clean, wm, *_ = models
    assert not adapters.detect(clean, SEED, PKH, CFG).accepted
    thief = P.pk_hash(hashlib.sha256(b"m4-thief").digest())
    assert not adapters.detect(wm, SEED, thief, CFG).accepted


def test_regulariser_uses_protocol_ordering(models):
    _, wm, *_ = models
    kernel, layout = adapters.get_kernel(wm, "conv2")
    assert layout == "OIHW" and kernel.shape == (64, 32, 3, 3)
    reg = TorchWatermark.derive(CFG, SEED, PKH)
    w_train = reg.vector(wm).detach().double().cpu().numpy()
    np.testing.assert_allclose(w_train, P.uchida_vector(kernel, layout), rtol=0, atol=1e-7)
    X, b = watermark_key(CFG, SEED, PKH)
    logits = X.astype(np.float64) @ P.uchida_vector(kernel, layout)
    bce = np.mean(np.logaddexp(0, logits) - b * logits)
    assert float(reg.loss(wm).detach()) == pytest.approx(bce, rel=1e-4, abs=1e-6)
    assert "X" not in repr(reg) and str(SEED) not in repr(reg)


def test_regulariser_hook_in_own_loop():
    """The hook form: a user's loop adds wm.loss(model); only the layer's weights need to move."""
    torch.manual_seed(1)
    model = wm_core.Net()
    wm = TorchWatermark.derive(CFG, SEED, PKH, lam=1.0)
    opt = torch.optim.Adam([model.conv2.weight], lr=1e-3)
    assert wm.errors(model) > CFG.max_err
    for _ in range(300):
        opt.zero_grad()
        wm.loss(model).backward()
        opt.step()
    assert adapters.detect(model, SEED, PKH, CFG).accepted


def test_linear_layer_and_dotted_names():
    class Block(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv2d(8, 8, 3, padding=1)
            self.conv2 = nn.Conv2d(8, 16, 3, padding=1)

    class Deep(nn.Module):
        def __init__(self):
            super().__init__()
            self.layer3 = nn.Sequential(Block(), Block())
            self.head = nn.Linear(16, 4)

    m = Deep()
    k, layout = adapters.get_kernel(m, "layer3.1.conv2")
    assert layout == "OIHW" and np.array_equal(k, m.layer3[1].conv2.weight.detach().numpy())
    k2, layout2 = adapters.get_kernel(m.state_dict(), "layer3.1.conv2")
    assert layout2 == "OIHW" and np.array_equal(k, k2)
    k3, layout3 = adapters.get_kernel(m, "head")
    assert layout3 == "OI" and adapters.uchida_vector(m, "head").shape == (16,)
    np.testing.assert_allclose(uchida_tensor(m.head.weight).detach().double().numpy(),
                               P.uchida_vector(k3, "OI"), rtol=0, atol=1e-7)
    with pytest.raises(adapters.LayerNotFoundError, match="layer3.1.conv2"):
        adapters.get_kernel(m, "layer3.2.conv2")
    with pytest.raises(adapters.LayerNotFoundError, match="Sequential"):
        adapters.get_kernel(m, "layer3")
    with pytest.raises(ValueError, match="cfg.M = 288"):
        embed_torch(m, (torch.zeros(1, 8, 4, 4), torch.zeros(1, dtype=torch.long)), P.Config(layer="head"),
                    SEED, PKH, epochs=1)


# ------------------------------------------------------------------ files and safe loading
def test_state_dict_files(models, tmp_path):
    _, wm, *_ = models
    want = adapters.quantized_vector(wm, CFG)
    sd = {k: v.detach().cpu() for k, v in wm.state_dict().items()}
    torch.save(sd, tmp_path / "wm.pt")
    torch.save({"epoch": 2, "state_dict": sd}, tmp_path / "ckpt.pth")
    torch.save({f"module.{k}": v for k, v in sd.items()}, tmp_path / "dp.pt")
    for name in ("wm.pt", "ckpt.pth", "dp.pt"):
        assert np.array_equal(adapters.quantized_vector(tmp_path / name, CFG), want), name
        assert adapters.detect(str(tmp_path / name), SEED, PKH, CFG).accepted
    with pytest.raises(adapters.FileTooLargeError):
        adapters.get_kernel(tmp_path / "wm.pt", "conv2", max_bytes=1000)


def test_torch_load_always_weights_only(models, tmp_path, monkeypatch):
    _, wm, *_ = models
    torch.save(wm.state_dict(), tmp_path / "wm.pt")
    calls = []
    real = torch.load

    def spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(torch, "load", spy)
    adapters.get_kernel(tmp_path / "wm.pt", "conv2")
    adapters.get_kernel(tmp_path / "wm.pt", "conv2", trust=True)      # trust never enables pickle
    assert calls and all(kw.get("weights_only") is True for kw in calls)


class _Evil:
    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (os.mkdir, (self.path,))


def test_pickled_code_refused(tmp_path):
    marker = tmp_path / "PWNED"
    torch.save({"conv2.weight": torch.zeros(2, 2), "x": _Evil(str(marker))}, tmp_path / "evil.pt")
    with pytest.raises(adapters.UnsafeModelError, match="never unpickles"):
        adapters.get_kernel(tmp_path / "evil.pt", "conv2")
    assert not marker.exists()
    torch.save(wm_core.Net(), tmp_path / "full.pt")                    # a whole pickled nn.Module
    with pytest.raises(adapters.UnsafeModelError, match="state_dict"):
        adapters.get_kernel(tmp_path / "full.pt", "conv2")
    torch.jit.save(torch.jit.script(wm_core.Net()), tmp_path / "ts.pt")
    with pytest.raises(adapters.UnsafeModelError, match="TorchScript"):
        adapters.get_kernel(tmp_path / "ts.pt", "conv2")
    (tmp_path / "junk.pt").write_bytes(b"not a torch file")
    with pytest.raises(adapters.AdapterError):
        adapters.get_kernel(tmp_path / "junk.pt", "conv2")


# ------------------------------------------------------------------ PyTorch -> ONNX (WM-05)
@pytest.mark.parametrize("dynamo", [True, False], ids=["dynamo", "torchscript"])
def test_onnx_export_gives_identical_vector(models, tmp_path, dynamo):
    pytest.importorskip("onnx")
    _, wm, det, *_ = models
    cpu = wm_core.Net()
    cpu.load_state_dict({k: v.cpu() for k, v in wm.state_dict().items()})
    cpu.eval()
    path = tmp_path / "wm.onnx"
    t = time.time()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            torch.onnx.export(cpu, (torch.zeros(1, 1, 28, 28),), str(path), dynamo=dynamo,
                              input_names=["x"], output_names=["logits"])
        except Exception as e:                              # the TorchScript exporter is deprecated
            if dynamo:
                raise
            pytest.skip(f"legacy exporter unavailable: {e}")
    print(f"\n[torch->onnx {'dynamo' if dynamo else 'torchscript'}] export {time.time() - t:.1f}s, "
          f"files: {sorted(p.name for p in tmp_path.iterdir())}")
    k_onnx, layout = adapters.get_kernel(path, "conv2")
    k_torch, _ = adapters.get_kernel(wm, "conv2")
    assert layout == "OIHW" and np.array_equal(k_onnx, k_torch)
    q_onnx, q_torch = adapters.quantized_vector(path, CFG), adapters.quantized_vector(wm, CFG)
    assert np.array_equal(q_onnx, q_torch)
    assert P.w_hash(q_onnx, CFG) == P.w_hash(q_torch, CFG)            # a proof binds to either file
    assert adapters.detect(path, SEED, PKH, CFG) == det
    k_fc, layout_fc = adapters.get_kernel(path, "fc1")                # Gemm transB=1 -> OI
    assert layout_fc == "OI" and np.array_equal(k_fc, wm.fc1.weight.detach().cpu().numpy())


def test_onnx_export_of_conv_followed_by_batchnorm(tmp_path):
    """Exporters fold an eval-mode BatchNorm into the preceding conv's kernel, which changes the Uchida
    vector. Exporting with optimize=False keeps the trained kernel, so the vector is identical."""
    pytest.importorskip("onnx")
    m = nn.Sequential()
    m.add_module("conv1", nn.Conv2d(1, 8, 3))
    m.add_module("bn1", nn.BatchNorm2d(8))
    m.add_module("conv2", nn.Conv2d(8, 16, 3))
    with torch.no_grad():
        m.bn1.running_var.uniform_(0.5, 2.0)
        m.bn1.weight.uniform_(0.5, 2.0)
    m.eval()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        torch.onnx.export(m, (torch.zeros(1, 1, 10, 10),), str(tmp_path / "bn.onnx"), dynamo=True, optimize=False)
    assert np.array_equal(adapters.uchida_vector(tmp_path / "bn.onnx", "conv1"), adapters.uchida_vector(m, "conv1"))
