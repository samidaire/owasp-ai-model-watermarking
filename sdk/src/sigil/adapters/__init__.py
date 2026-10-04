"""Framework adapters (WM-03, WM-04, WM-05): read a named layer's kernel from PyTorch, Keras or ONNX.

The common interface works on an in-memory model or a model file, with the framework detected from the
object's type or the file extension (.pt/.pth, .keras/.h5/.hdf5, .onnx)::

    from sigil import adapters, protocol as P
    kernel, layout = adapters.get_kernel("model.onnx", "conv2")      # e.g. (array (64,32,3,3), "OIHW")
    w = adapters.uchida_vector("model.keras", "conv2")                # == P.uchida_vector(kernel, layout)
    det = adapters.detect(model, seed, pk_hash, cfg)                  # P.Detection on the quantised vector

Every file loader is safe by default (SDK-04): torch.load(weights_only=True) only, Keras safe_mode=True
with Lambda layers refused unless trust=True, onnx.checker plus external-data path checks, and a size
limit (max_bytes, default 2 GiB). Framework libraries are imported lazily: `import sigil.adapters` does
not import torch, TensorFlow/Keras or onnx.

Embedding helpers live in the framework modules (`TorchWatermark`, `finetune_embed`,
`KerasWatermark`, `UchidaRegularizer`) and are re-exported here lazily; `sigil.embed` wraps them.
"""
from __future__ import annotations

import importlib

import numpy as np

from .. import protocol as P
from ._common import (DEFAULT_MAX_BYTES, EXTENSIONS, FRAMEWORKS, AdapterError, FileTooLargeError,
                      LayerNotFoundError, UnsafeModelError, check_file, detect_framework)

_MODULES = {"torch": "torch_adapter", "keras": "keras_adapter", "onnx": "onnx_adapter"}
_LAZY = {
    "TorchWatermark": "torch_adapter", "finetune_embed": "torch_adapter", "load_torch": "torch_adapter",
    "KerasWatermark": "keras_adapter", "UchidaRegularizer": "keras_adapter", "load_keras": "keras_adapter",
    "load_onnx": "onnx_adapter",
}

__all__ = [
    "DEFAULT_MAX_BYTES", "EXTENSIONS", "FRAMEWORKS", "AdapterError", "FileTooLargeError",
    "LayerNotFoundError", "UnsafeModelError", "check_file", "detect_framework", "adapter",
    "get_kernel", "uchida_vector", "quantized_vector", "detect", *_LAZY,
]


def adapter(framework: str):
    """The adapter module for 'torch', 'keras' or 'onnx' (imports that framework)."""
    if framework not in _MODULES:
        raise AdapterError(f"unknown framework {framework!r}; expected one of {FRAMEWORKS}")
    return importlib.import_module(f".{_MODULES[framework]}", __name__)


def get_kernel(model_or_path, layer: str, *, framework: str | None = None, trust: bool = False,
               max_bytes: int | None = DEFAULT_MAX_BYTES) -> tuple[np.ndarray, str]:
    """The kernel of `layer` as a numpy array, with its layout ('OIHW', 'HWIO', 'OI' or 'IO').

    model_or_path: a torch.nn.Module or state_dict, a keras.Model, an onnx.ModelProto, or a path to a
    .pt/.pth, .keras/.h5/.hdf5 or .onnx file. trust=True allows Keras files that need unsafe
    deserialisation (Lambda layers); it never enables pickle for PyTorch files.
    """
    fw = framework or detect_framework(model_or_path)
    return adapter(fw).get_kernel(model_or_path, layer, trust=trust, max_bytes=max_bytes)


def uchida_vector(model_or_path, layer: str, **kw) -> np.ndarray:
    """protocol.uchida_vector of the layer: mean over output units, canonical (in, kh, kw) order."""
    kernel, layout = get_kernel(model_or_path, layer, **kw)
    return P.uchida_vector(kernel, layout)


def quantized_vector(model_or_path, cfg: P.Config, **kw) -> np.ndarray:
    """protocol.quantize of the Uchida vector of cfg.layer: the w_q the circuit and w_hash use."""
    return P.quantize(uchida_vector(model_or_path, cfg.layer, **kw), cfg)


def detect(model_or_path, seed: int, pk_hash: int, cfg: P.Config, **kw) -> P.Detection:
    """Owner-side protocol-v2 detection on the quantised Uchida vector of cfg.layer."""
    return P.detect(seed, pk_hash, cfg, quantized_vector(model_or_path, cfg, **kw))


def __getattr__(name):
    if name in _LAZY:
        return getattr(importlib.import_module(f".{_LAZY[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
