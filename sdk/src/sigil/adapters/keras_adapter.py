"""TensorFlow/Keras adapter (WM-04): read a Conv2D/Dense kernel and embed the Uchida watermark.

Reading works on an in-memory keras.Model (nested models as ``"outer/inner"``) or a .keras/.h5/.hdf5
file. Files are loaded with ``keras.models.load_model(path, safe_mode=True, compile=False)`` after a
pre-scan of the saved architecture (SDK-04): a model containing a Lambda layer (arbitrary Python
bytecode) is refused unless the caller passes ``trust=True``; a .keras archive whose uncompressed size
exceeds the limit is refused (zip-bomb guard). Layouts: Conv2D HWIO, Dense IO.

Embedding uses a Keras regulariser attached to the layer's kernel *variable*, so it is added to the
loss by ``model.fit`` but never written into the saved model's config (the regulariser holds the
secret key, CR-04). The Uchida vector is taken in the canonical order: HWIO is transposed to OIHW
before the mean and flatten, so the same X works across frameworks::

    wm = KerasWatermark.derive(cfg, seed, pk_hash, lam=1.0)
    with wm.attached(model):
        model.fit(x, y, epochs=2, callbacks=[wm.callback()])
"""
from __future__ import annotations

import contextlib
import json
import os
import zipfile

import keras
import numpy as np
from keras import ops

from .. import protocol as P
from ._common import (DEFAULT_MAX_BYTES, AdapterError, FileTooLargeError, LayerNotFoundError,
                      UnsafeModelError, check_file)

UNSAFE_CLASSES = {"Lambda", "__lambda__"}     # Python bytecode inside the saved config


# ------------------------------------------------------------------ safe loading
def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def unsafe_layers(config: dict) -> list[str]:
    """Names of objects in a saved model config whose deserialisation could run arbitrary code."""
    found = []
    for d in _walk(config):
        if d.get("class_name") in UNSAFE_CLASSES or d.get("function_type") == "lambda":
            cfg = d.get("config") if isinstance(d.get("config"), dict) else {}
            found.append(f"{d.get('class_name')}:{cfg.get('name', d.get('name', '?'))}")
    return found


def _read_config(p, max_bytes) -> dict:
    suffix = p.suffix.lower()
    if suffix == ".keras":
        if not zipfile.is_zipfile(p):
            raise AdapterError(f"{p.name} is not a .keras (zip) archive")
        with zipfile.ZipFile(p) as z:
            total = sum(i.file_size for i in z.infolist())
            if max_bytes is not None and total > max_bytes:
                raise FileTooLargeError(f"{p.name} expands to {total} bytes, above the limit of {max_bytes}")
            if "config.json" not in z.namelist():
                raise AdapterError(f"{p.name} has no config.json: not a Keras v3 model archive")
            return json.loads(z.read("config.json"))
    import h5py                                              # a Keras dependency
    try:
        f = h5py.File(p, "r")
    except OSError as e:
        raise AdapterError(f"{p.name} is not a readable HDF5 file: {e}") from None
    with f:
        raw = f.attrs.get("model_config")
        if raw is None:
            raise AdapterError(f"{p.name} holds weights only (no model_config); build the model, call "
                               f"load_weights yourself and pass the keras.Model object instead")
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


def load_keras(path, *, trust: bool = False, max_bytes: int | None = DEFAULT_MAX_BYTES):
    """Load a .keras/.h5/.hdf5 model safely: size limit, Lambda pre-scan, safe_mode=True, compile=False."""
    p = check_file(path, max_bytes)
    if p.suffix.lower() not in (".keras", ".h5", ".hdf5"):
        raise AdapterError(f"{p.name}: expected a .keras, .h5 or .hdf5 file")
    bad = unsafe_layers(_read_config(p, max_bytes))
    if bad and not trust:
        raise UnsafeModelError(f"{p.name} contains layers that need unsafe deserialisation ({', '.join(bad)}); "
                               f"loading them can execute arbitrary code. Pass trust=True (CLI: --trust) only "
                               f"for files from a trusted source.")
    try:
        return keras.models.load_model(str(p), safe_mode=not trust, compile=False)
    except ValueError as e:
        if "safe_mode" in str(e) or "unsafe" in str(e).lower():
            raise UnsafeModelError(f"{p.name}: Keras refused unsafe deserialisation: {e}") from None
        raise


# ------------------------------------------------------------------ reading a layer
def _layer(model, layer: str):
    obj = model
    for part in layer.split("/"):
        try:
            obj = obj.get_layer(part)
        except (ValueError, AttributeError):
            names = [lyr.name for lyr in getattr(model, "layers", [])]
            raise LayerNotFoundError(f"no layer {layer!r} in model {model.name!r}; layers: {names}") from None
    if not isinstance(obj, (keras.layers.Conv2D, keras.layers.Dense)):
        raise LayerNotFoundError(f"layer {layer!r} is a {type(obj).__name__}; only Conv2D and Dense layers "
                                 f"can carry the watermark")
    if not obj.built:
        raise LayerNotFoundError(f"layer {layer!r} is not built yet (call the model on an input first)")
    return obj


def _layout(lyr) -> str:
    return "HWIO" if isinstance(lyr, keras.layers.Conv2D) else "IO"


def get_kernel(model_or_path, layer: str, *, trust: bool = False,
               max_bytes: int | None = DEFAULT_MAX_BYTES) -> tuple[np.ndarray, str]:
    """(kernel, layout) of a Conv2D (HWIO) or Dense (IO) layer of a keras.Model or a saved file."""
    model = model_or_path
    if isinstance(model_or_path, (str, os.PathLike)):
        model = load_keras(model_or_path, trust=trust, max_bytes=max_bytes)
    lyr = _layer(model, layer)
    return np.asarray(ops.convert_to_numpy(lyr.kernel)), _layout(lyr)


# ------------------------------------------------------------------ embedding
def uchida_tensor(kernel, layout: str):
    """Differentiable Uchida vector in the canonical order: HWIO -> OIHW (IO -> OI), mean over O, flatten."""
    k = ops.transpose(kernel, (3, 2, 0, 1)) if layout == "HWIO" else ops.transpose(kernel, (1, 0))
    return ops.reshape(ops.mean(k, axis=0), (-1,))


class UchidaRegularizer(keras.regularizers.Regularizer):
    """lam * mean BCE-with-logits(X @ w, b) on a kernel; w is its canonical Uchida vector.

    It holds the secret key, so it refuses to serialise (get_config raises): attach it with
    KerasWatermark.attach rather than as a layer's kernel_regularizer, which Keras would save.
    """

    def __init__(self, X, b, layout: str, lam: float = 1.0, previous=None):
        if layout not in ("HWIO", "IO"):
            raise ValueError("layout must be 'HWIO' (Conv2D) or 'IO' (Dense)")
        self._X = np.asarray(X, dtype=np.float32)
        self._b = np.asarray(b, dtype=np.float32)
        self.layout, self.lam, self.previous = layout, float(lam), previous

    def __call__(self, kernel):
        w = uchida_tensor(kernel, self.layout)
        logits = ops.matmul(ops.convert_to_tensor(self._X, dtype=w.dtype), w)
        b = ops.convert_to_tensor(self._b, dtype=w.dtype)
        loss = self.lam * ops.mean(ops.binary_crossentropy(b, logits, from_logits=True))
        if self.previous is not None:                         # keep the user's own kernel regulariser
            loss = loss + self.previous(kernel)
        return loss

    def get_config(self):
        raise TypeError("UchidaRegularizer holds the secret watermark key and must not be serialised; "
                        "attach it with KerasWatermark.attach() and detach it before saving")

    def __repr__(self) -> str:
        return f"UchidaRegularizer(layout={self.layout!r}, T={self._X.shape[0]}, M={self._X.shape[1]}, lam={self.lam})"


class KerasWatermark:
    """The Uchida regulariser for one named Conv2D/Dense layer of a Keras model.

    Holds the secret key X (T x M) and signature b (T): keep it out of logs, saved models and results.
    """

    def __init__(self, X, b, layer: str, lam: float = 1.0):
        X = np.asarray(X)
        b = np.asarray(b)
        if X.ndim != 2 or b.shape != (X.shape[0],):
            raise ValueError(f"expected X of shape (T, M) and b of shape (T,), got {X.shape} and {b.shape}")
        if not np.isin(b, (0, 1)).all():
            raise ValueError("signature bits must be 0 or 1")
        self.layer, self.lam = layer, float(lam)
        self.T, self.M = X.shape
        self._X = X.astype(np.float32)
        self._b = b.astype(np.float32)
        self._attached = {}

    @classmethod
    def derive(cls, cfg: P.Config, seed: int, pk_hash: int, lam: float = 1.0) -> "KerasWatermark":
        """Key and signature per protocol v2 (key_matrix, signature_bits) for cfg.layer."""
        return cls(P.key_matrix(seed, pk_hash, cfg), P.signature_bits(seed, pk_hash, cfg), cfg.layer, lam)

    def __repr__(self) -> str:
        return f"KerasWatermark(layer={self.layer!r}, T={self.T}, M={self.M}, lam={self.lam})"

    def _check(self, model):
        lyr = _layer(model, self.layer)
        m = int(np.prod(lyr.kernel.shape[:-1]))              # H*W*I (conv) or I (dense)
        if m != self.M:
            raise ValueError(f"layer {self.layer!r} has a Uchida vector of length {m}, key expects M={self.M}")
        return lyr

    def regularizer(self, layout: str = "HWIO", previous=None) -> UchidaRegularizer:
        return UchidaRegularizer(self._X, self._b, layout, self.lam, previous)

    def attach(self, model) -> None:
        """Add the regulariser to the layer's kernel variable (model.fit then includes it in the loss)."""
        lyr = self._check(model)
        var = lyr.kernel
        if id(var) in self._attached:
            return
        previous = getattr(var, "regularizer", None)
        self._attached[id(var)] = (var, previous)
        var.regularizer = self.regularizer(_layout(lyr), previous)
        _reset_train_function(model)

    def detach(self, model) -> None:
        """Remove the regulariser again (restoring any previous kernel regulariser)."""
        lyr = _layer(model, self.layer)
        entry = self._attached.pop(id(lyr.kernel), None)
        if entry is not None:
            entry[0].regularizer = entry[1]
            _reset_train_function(model)

    @contextlib.contextmanager
    def attached(self, model):
        self.attach(model)
        try:
            yield model
        finally:
            self.detach(model)

    def errors(self, model) -> int:
        """Bit errors of the float (unquantised) projection: a cheap progress signal during training."""
        kernel, layout = get_kernel(model, self.layer)
        w = P.uchida_vector(kernel, layout)
        return int(np.count_nonzero((self._X @ w >= 0) != (self._b > 0.5)))

    def callback(self) -> keras.callbacks.Callback:
        """A callback that adds 'wm_errors' (float bit errors) to the epoch logs."""
        wm = self

        class _WatermarkMonitor(keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if logs is not None:
                    logs["wm_errors"] = wm.errors(self.model)

        return _WatermarkMonitor()


def _reset_train_function(model) -> None:
    # model.fit caches a traced train step; drop it so the (removed) regulariser is (no longer) included
    for attr in ("train_function", "test_function"):
        if getattr(model, attr, None) is not None:
            setattr(model, attr, None)
