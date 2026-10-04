"""Shared pieces of the framework adapters: errors, safe-loading limits and framework detection.

Nothing here imports torch, TensorFlow/Keras or onnx: the framework is recognised from the object's
class hierarchy (by module name) or from the file extension, so `import sigil.adapters` stays light.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_MAX_BYTES = 2 * 1024 ** 3      # SDK-04: refuse model files larger than 2 GiB unless raised explicitly

FRAMEWORKS = ("torch", "keras", "onnx")
EXTENSIONS = {
    ".pt": "torch", ".pth": "torch",
    ".keras": "keras", ".h5": "keras", ".hdf5": "keras",
    ".onnx": "onnx",
}


class AdapterError(ValueError):
    """A model or layer cannot be read by a framework adapter."""


class LayerNotFoundError(AdapterError, LookupError):
    """The named layer does not exist, is ambiguous, or is not a supported conv/linear layer."""


class UnsafeModelError(AdapterError):
    """Loading the file would need unsafe deserialisation (SDK-04); it was refused."""


class FileTooLargeError(UnsafeModelError):
    """The file (or its external data) exceeds the caller's size limit."""


def check_file(path, max_bytes: int | None = DEFAULT_MAX_BYTES) -> Path:
    """Return `path` as a Path after checking it is a regular file no larger than `max_bytes`."""
    p = Path(os.fspath(path))
    if not p.is_file():
        raise AdapterError(f"not a file: {p}")
    size = p.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise FileTooLargeError(f"{p.name} is {size} bytes, above the limit of {max_bytes} bytes "
                                f"(pass a larger max_bytes if you trust this file)")
    return p


def _mro(obj) -> list[tuple[str, str]]:
    return [((c.__module__ or ""), c.__name__) for c in type(obj).__mro__]


def detect_framework(model_or_path) -> str:
    """'torch', 'keras' or 'onnx' for an in-memory model or a model file path."""
    if isinstance(model_or_path, (str, os.PathLike)):
        suffix = Path(os.fspath(model_or_path)).suffix.lower()
        if suffix not in EXTENSIONS:
            raise AdapterError(f"unknown model file extension {suffix!r}; expected one of "
                               f"{sorted(EXTENSIONS)}")
        return EXTENSIONS[suffix]
    mro = _mro(model_or_path)
    if any(mod.startswith("torch.nn") and name == "Module" for mod, name in mro):
        return "torch"
    if any(mod.split(".")[0] in ("keras", "tf_keras") and name in ("Layer", "Model", "Operation")
           for mod, name in mro):
        return "keras"
    if any(mod.startswith("onnx") and name == "ModelProto" for mod, name in mro):
        return "onnx"
    if isinstance(model_or_path, Mapping) and model_or_path and all(
            any(mod.startswith("torch") and name == "Tensor" for mod, name in _mro(v))
            for v in model_or_path.values()):
        return "torch"                                   # an in-memory state_dict
    raise AdapterError(f"cannot tell the framework of a {type(model_or_path).__name__}; pass a "
                       f"torch.nn.Module/state_dict, a keras.Model, an onnx.ModelProto or a file path")


def layout_for_ndim(ndim: int, conv: str, dense: str, what: str) -> str:
    if ndim == 4:
        return conv
    if ndim == 2:
        return dense
    raise LayerNotFoundError(f"{what} has a {ndim}-D kernel; only 2-D convolutions (4-D kernels) and "
                             f"dense/linear layers (2-D kernels) are supported")
