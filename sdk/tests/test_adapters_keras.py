"""Keras adapter (WM-04), Keras -> ONNX via tf2onnx (WM-05), canonical cross-framework ordering, and
safe Keras loading (SDK-04).

A small Keras CNN whose watermarked Conv2D "conv2" has 32 input channels and a 3x3 kernel (M = 288),
so the protocol-v2 config (T=64, M=288) is the same one the PyTorch demo uses.
"""
import gzip
import hashlib
import json
import os
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
keras = pytest.importorskip("keras")
pytest.importorskip("tensorflow")

from sigil import adapters  # noqa: E402
from sigil import protocol as P  # noqa: E402
from sigil.adapters.keras_adapter import KerasWatermark, UchidaRegularizer  # noqa: E402
from sigil.embed import embed_keras  # noqa: E402

pytestmark = pytest.mark.ml

DATA = Path(__file__).resolve().parents[2] / "demo" / "data"
if not (DATA / "train-images-idx3-ubyte.gz").exists():
    pytest.skip("MNIST not found in demo/data", allow_module_level=True)

CFG = P.Config(T=64, M=288, layer="conv2", max_err=8)
PKH = P.pk_hash(hashlib.sha256(b"m4-keras-owner").digest())
SEED = int.from_bytes(hashlib.sha256(b"m4-keras-seed").digest(), "big") >> 8
N_TRAIN, EPOCHS = 10000, 2


def _idx(name):
    with gzip.open(DATA / name, "rb") as f:
        raw = f.read()
    dims = [int.from_bytes(raw[4 + 4 * i:8 + 4 * i], "big") for i in range(raw[3])]
    return np.frombuffer(raw, dtype=np.uint8, offset=4 + 4 * raw[3]).reshape(dims)


def _images(name, n=None):
    x = _idx(name)[:n].astype(np.float32) / 255.0
    return ((x - 0.1307) / 0.3081)[..., None]                       # NHWC


def build_cnn(name="kcnn"):
    inp = keras.Input((28, 28, 1), name="image")
    h = keras.layers.Conv2D(32, 3, activation="relu", name="conv1")(inp)
    h = keras.layers.Conv2D(64, 3, activation="relu", name="conv2")(h)   # watermarked: M = 32*3*3
    h = keras.layers.MaxPooling2D(2, name="pool")(h)
    h = keras.layers.Flatten(name="flatten")(h)
    out = keras.layers.Dense(10, name="fc")(h)
    return keras.Model(inp, out, name=name)


@pytest.fixture(scope="module")
def mnist():
    return (_images("train-images-idx3-ubyte.gz", N_TRAIN), _idx("train-labels-idx1-ubyte.gz")[:N_TRAIN].astype("int64"),
            _images("t10k-images-idx3-ubyte.gz"), _idx("t10k-labels-idx1-ubyte.gz").astype("int64"))


@pytest.fixture(scope="module")
def models(mnist):
    """(clean, watermarked, detection, acc_clean, acc_wm): same init and data order."""
    x, y, xt, yt = mnist
    keras.utils.set_random_seed(0)
    clean = build_cnn()
    clean.compile(optimizer=keras.optimizers.Adam(1e-3),
                  loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True), metrics=["accuracy"])
    keras.utils.set_random_seed(0)
    t = time.time()
    clean.fit(x, y, batch_size=128, epochs=EPOCHS, shuffle=True, verbose=0)
    t_clean = time.time() - t
    keras.utils.set_random_seed(0)
    wm = build_cnn()
    t = time.time()
    wm, det = embed_keras(wm, (x, y), CFG, SEED, PKH, epochs=EPOCHS, lam=1.0, train_seed=0)
    t_wm = time.time() - t
    acc_clean = clean.evaluate(xt, yt, verbose=0)[1]
    acc_wm = wm.evaluate(xt, yt, verbose=0)[1]
    print(f"\n[keras cpu] clean acc={acc_clean:.4f} wm acc={acc_wm:.4f} cost={100 * (acc_clean - acc_wm):.2f}pp "
          f"errors={det.errors}/{CFG.T} clean-model errors={adapters.detect(clean, SEED, PKH, CFG).errors} "
          f"train clean {t_clean:.1f}s wm {t_wm:.1f}s")
    return clean, wm, det, acc_clean, acc_wm


# ------------------------------------------------------------------ embedding and detection
def test_watermark_accepted_with_small_accuracy_cost(models):
    clean, wm, det, acc_clean, acc_wm = models
    assert det.accepted and det.errors <= CFG.max_err
    assert acc_wm > 0.94
    assert acc_clean - acc_wm < 0.01
    assert not adapters.detect(clean, SEED, PKH, CFG).accepted
    thief = P.pk_hash(hashlib.sha256(b"m4-thief").digest())
    assert not adapters.detect(wm, SEED, thief, CFG).accepted


def test_kernel_layouts(models):
    _, wm, *_ = models
    k, layout = adapters.get_kernel(wm, "conv2")
    assert layout == "HWIO" and k.shape == (3, 3, 32, 64)
    kd, layout_d = adapters.get_kernel(wm, "fc")
    assert layout_d == "IO" and adapters.uchida_vector(wm, "fc").shape == (kd.shape[0],)
    with pytest.raises(adapters.LayerNotFoundError, match="layers"):
        adapters.get_kernel(wm, "conv9")
    with pytest.raises(adapters.LayerNotFoundError, match="MaxPooling2D"):
        adapters.get_kernel(wm, "pool")


def test_regulariser_matches_protocol(models):
    """The training-time regulariser uses the canonical vector and the same BCE as PyTorch."""
    _, wm, *_ = models
    k, layout = adapters.get_kernel(wm, "conv2")
    X, b = P.key_matrix(SEED, PKH, CFG), P.signature_bits(SEED, PKH, CFG)
    reg = UchidaRegularizer(X, b, "HWIO", lam=1.0)
    logits = X.astype(np.float64) @ P.uchida_vector(k, layout)
    bce = np.mean(np.logaddexp(0, logits) - b * logits)
    assert float(keras.ops.convert_to_numpy(reg(keras.ops.convert_to_tensor(k)))) == pytest.approx(bce, rel=1e-4, abs=1e-6)
    with pytest.raises(TypeError, match="secret"):
        reg.get_config()
    assert str(SEED) not in repr(reg) and "X=" not in repr(KerasWatermark(X, b, "conv2"))


def test_saved_files_detect_and_hold_no_key(models, tmp_path):
    _, wm, det, *_ = models
    want = adapters.quantized_vector(wm, CFG)
    wm.save(tmp_path / "wm.keras")
    wm.save(tmp_path / "wm.h5")
    for name in ("wm.keras", "wm.h5"):
        q = adapters.quantized_vector(tmp_path / name, CFG)
        assert np.array_equal(q, want), name
        assert adapters.detect(tmp_path / name, SEED, PKH, CFG) == det
    cfg_json = zipfile.ZipFile(tmp_path / "wm.keras").read("config.json").decode()
    assert "Uchida" not in cfg_json
    conv2 = next(lyr for lyr in json.loads(cfg_json)["config"]["layers"] if lyr["config"]["name"] == "conv2")
    assert conv2["config"]["kernel_regularizer"] is None              # the key was never attached to the config
    with pytest.raises(adapters.FileTooLargeError):
        adapters.get_kernel(tmp_path / "wm.keras", "conv2", max_bytes=1000)


def test_attached_regulariser_is_removed_and_composes(mnist):
    """attach/detach restores a user's own kernel regulariser; fit then optimises both terms."""
    x, y, *_ = mnist
    keras.utils.set_random_seed(1)
    m = build_cnn("kcnn_l2")
    l2 = keras.regularizers.L2(1e-4)
    m.get_layer("conv2").kernel.regularizer = l2
    m.compile(optimizer="adam", loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True))
    wm = KerasWatermark.derive(CFG, SEED, PKH)
    with wm.attached(m):
        assert isinstance(m.get_layer("conv2").kernel.regularizer, UchidaRegularizer)
        m.fit(x[:2048], y[:2048], batch_size=128, epochs=1, verbose=0)
    assert m.get_layer("conv2").kernel.regularizer is l2


# ------------------------------------------------------------------ Keras -> ONNX (WM-05)
def test_tf2onnx_export_gives_identical_vector(models, tmp_path):
    tf2onnx = pytest.importorskip("tf2onnx")
    import tensorflow as tf
    _, wm, det, *_ = models
    path = tmp_path / "wm.onnx"
    t = time.time()
    tf2onnx.convert.from_keras(wm, input_signature=(tf.TensorSpec((None, 28, 28, 1), tf.float32, name="image"),),
                               opset=17, output_path=str(path))
    print(f"\n[keras->onnx tf2onnx] convert {time.time() - t:.1f}s")
    k_onnx, layout = adapters.get_kernel(path, "conv2")
    k_keras, _ = adapters.get_kernel(wm, "conv2")
    assert layout == "OIHW" and np.array_equal(k_onnx, np.transpose(k_keras, (3, 2, 0, 1)))
    q_onnx, q_keras = adapters.quantized_vector(path, CFG), adapters.quantized_vector(wm, CFG)
    assert np.array_equal(q_onnx, q_keras)
    assert P.w_hash(q_onnx, CFG) == P.w_hash(q_keras, CFG)
    assert adapters.detect(path, SEED, PKH, CFG) == det
    assert np.array_equal(adapters.uchida_vector(path, "fc"), adapters.uchida_vector(wm, "fc"))  # MatMul, IO


# ------------------------------------------------------------------ canonical ordering across frameworks
def test_torch_kernel_in_keras_gives_identical_vector(tmp_path):
    """A PyTorch conv2 kernel copied into a Keras Conv2D (OIHW -> HWIO) has the identical Uchida vector,
    and a PyTorch watermark stays detectable from the Keras model and from its tf2onnx export."""
    torch = pytest.importorskip("torch")
    tnet = torch.nn.Sequential()
    tnet.add_module("conv1", torch.nn.Conv2d(1, 32, 3))
    tnet.add_module("conv2", torch.nn.Conv2d(32, 64, 3))
    torch.manual_seed(3)
    for mod in tnet:
        mod.reset_parameters()
    reg = adapters.TorchWatermark.derive(CFG, SEED, PKH)
    opt = torch.optim.Adam([tnet.conv2.weight], lr=1e-3)
    for _ in range(300):                                    # embed into conv2 directly (no data needed)
        opt.zero_grad()
        reg.loss(tnet).backward()
        opt.step()
    kmodel = build_cnn("kcopy")
    for name in ("conv1", "conv2"):
        mod = getattr(tnet, name)
        kmodel.get_layer(name).set_weights([np.transpose(mod.weight.detach().numpy(), (2, 3, 1, 0)),
                                            mod.bias.detach().numpy()])
    w_torch = adapters.uchida_vector(tnet, "conv2")
    w_keras = adapters.uchida_vector(kmodel, "conv2")
    assert np.array_equal(w_torch, w_keras)
    assert np.array_equal(adapters.quantized_vector(tnet, CFG), adapters.quantized_vector(kmodel, CFG))
    det = adapters.detect(tnet, SEED, PKH, CFG)
    assert det.accepted and adapters.detect(kmodel, SEED, PKH, CFG) == det
    tf2onnx = pytest.importorskip("tf2onnx")
    import tensorflow as tf
    tf2onnx.convert.from_keras(kmodel, input_signature=(tf.TensorSpec((None, 28, 28, 1), tf.float32),),
                               opset=17, output_path=str(tmp_path / "k.onnx"))
    assert np.array_equal(adapters.uchida_vector(tmp_path / "k.onnx", "conv2"), w_torch)


# ------------------------------------------------------------------ safe loading (SDK-04)
def _lambda_model():
    inp = keras.Input((4,), name="x")
    h = keras.layers.Lambda(lambda t: t * 2.0, name="double")(inp)
    out = keras.layers.Dense(3, name="dense")(h)
    return keras.Model(inp, out, name="with_lambda")


@pytest.mark.parametrize("ext", [".keras", ".h5"])
def test_lambda_layer_refused_unless_trusted(tmp_path, ext):
    m = _lambda_model()
    path = tmp_path / f"lambda{ext}"
    m.save(path)
    with pytest.raises(adapters.UnsafeModelError, match="trust=True"):
        adapters.get_kernel(path, "dense")
    with pytest.raises(adapters.UnsafeModelError):
        adapters.load_keras(path)
    k, layout = adapters.get_kernel(path, "dense", trust=True)
    assert layout == "IO" and np.array_equal(k, keras.ops.convert_to_numpy(m.get_layer("dense").kernel))


def test_weights_only_h5_and_bad_archives_rejected(tmp_path):
    m = build_cnn("kw")
    m.save_weights(tmp_path / "w.weights.h5")
    os.replace(tmp_path / "w.weights.h5", tmp_path / "w.h5")
    with pytest.raises(adapters.AdapterError, match="weights only"):
        adapters.get_kernel(tmp_path / "w.h5", "conv2")
    (tmp_path / "junk.keras").write_bytes(b"not a zip")
    with pytest.raises(adapters.AdapterError, match="zip"):
        adapters.get_kernel(tmp_path / "junk.keras", "conv2")
    (tmp_path / "junk.h5").write_bytes(b"not an hdf5 file")
    with pytest.raises(adapters.AdapterError, match="HDF5"):
        adapters.get_kernel(tmp_path / "junk.h5", "conv2")
    with zipfile.ZipFile(tmp_path / "bomb.keras", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.json", "{}")
        z.writestr("model.weights.h5", b"\0" * 4_000_000)           # compresses to a few KB
    assert (tmp_path / "bomb.keras").stat().st_size < 100_000
    with pytest.raises(adapters.FileTooLargeError, match="expands"):
        adapters.get_kernel(tmp_path / "bomb.keras", "conv2", max_bytes=1_000_000)
