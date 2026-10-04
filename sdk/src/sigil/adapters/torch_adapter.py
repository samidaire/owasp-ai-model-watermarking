"""PyTorch adapter (WM-03): read a Conv2d/Linear kernel and embed the Uchida watermark in training.

Reading works on an in-memory nn.Module (dotted names such as ``layer3.1.conv2``), an in-memory
state_dict, or a .pt/.pth file. Files are only ever opened with
``torch.load(path, map_location="cpu", weights_only=True)`` (SDK-04): a full pickled nn.Module or a
TorchScript archive is refused, never unpickled. Layouts: Conv2d OIHW, Linear OI.

Embedding (WM-01/WM-03) is a regulariser for the user's own training loop::

    wm = TorchWatermark.derive(cfg, seed, pk_hash, lam=1.0)     # or TorchWatermark(X, b, "conv2")
    for x, y in loader:
        loss = F.cross_entropy(model(x), y) + wm.loss(model)    # lam * BCE-with-logits(X @ w, b)
        ...

plus `finetune_embed(model, data, X, b, epochs, layer=...)`, which runs such a loop for you.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .. import protocol as P
from ._common import DEFAULT_MAX_BYTES, AdapterError, LayerNotFoundError, UnsafeModelError, check_file

_CHECKPOINT_KEYS = ("state_dict", "model_state_dict", "model", "net", "module")


# ------------------------------------------------------------------ safe loading
def load_torch(path, *, max_bytes: int | None = DEFAULT_MAX_BYTES) -> dict[str, torch.Tensor]:
    """Load a state_dict from a .pt/.pth file with weights_only=True; never unpickles code.

    Accepts a plain state_dict or a checkpoint dict holding one under a common key
    ('state_dict', 'model_state_dict', 'model', 'net', 'module').
    """
    p = check_file(path, max_bytes)
    try:
        obj = torch.load(p, map_location="cpu", weights_only=True)
    except Exception as e:                                  # UnpicklingError, RuntimeError, ...
        msg = str(e)
        if "TorchScript" in msg:
            raise UnsafeModelError(
                f"{p.name} is a TorchScript archive; sigil reads weights only. Save "
                f"model.state_dict() with torch.save and load that instead.") from None
        if "Weights only load failed" in msg or "Unsupported global" in msg:
            raise UnsafeModelError(
                f"{p.name} contains pickled Python objects (for example a whole nn.Module saved with "
                f"torch.save(model)); sigil never unpickles untrusted files (weights_only=True). "
                f"Re-save it with torch.save(model.state_dict(), path).") from None
        raise AdapterError(f"{p.name} is not a readable PyTorch weights file: {type(e).__name__}: {msg}") from None
    return _state_dict(obj, p.name)


def _is_tensor_map(obj) -> bool:
    return isinstance(obj, Mapping) and any(isinstance(v, torch.Tensor) for v in obj.values())


def _state_dict(obj, what: str) -> dict[str, torch.Tensor]:
    if _is_tensor_map(obj):
        return {k: v for k, v in obj.items() if isinstance(v, torch.Tensor)}
    if isinstance(obj, Mapping):
        for key in _CHECKPOINT_KEYS:
            if _is_tensor_map(obj.get(key)):
                return {k: v for k, v in obj[key].items() if isinstance(v, torch.Tensor)}
    raise AdapterError(f"{what} does not contain a state_dict (a mapping of parameter names to tensors)")


# ------------------------------------------------------------------ reading a layer
def _module_weight(model: nn.Module, layer: str) -> torch.Tensor:
    try:
        mod = model.get_submodule(layer)
    except AttributeError:
        names = [n for n, m in model.named_modules() if isinstance(m, (nn.Conv2d, nn.Linear))]
        raise LayerNotFoundError(f"no layer {layer!r} in {type(model).__name__}; conv/linear layers: "
                                 f"{names}") from None
    if not isinstance(mod, (nn.Conv2d, nn.Linear)):
        raise LayerNotFoundError(f"layer {layer!r} is a {type(mod).__name__}; only Conv2d and Linear "
                                 f"layers can carry the watermark")
    return mod.weight


def _state_dict_weight(sd: Mapping, layer: str) -> torch.Tensor:
    for key in (f"{layer}.weight", f"module.{layer}.weight", layer):
        if key in sd and isinstance(sd[key], torch.Tensor) and sd[key].ndim in (2, 4):
            return sd[key]
    names = sorted(k[:-len(".weight")] for k, v in sd.items()
                   if k.endswith(".weight") and isinstance(v, torch.Tensor) and v.ndim in (2, 4))
    raise LayerNotFoundError(f"no 2-D/4-D weight '{layer}.weight' in the state_dict; candidates: {names}")


def _to_numpy(w: torch.Tensor) -> np.ndarray:
    w = w.detach().cpu()
    if w.dtype not in (torch.float32, torch.float64):
        w = w.float()                                       # half/bfloat16 -> float32 (exact)
    return w.numpy()


def get_kernel(model_or_path, layer: str, *, trust: bool = False,
               max_bytes: int | None = DEFAULT_MAX_BYTES) -> tuple[np.ndarray, str]:
    """(kernel, layout) of a Conv2d (OIHW) or Linear (OI) layer.

    `trust` is accepted for interface symmetry and has no effect: PyTorch files are never unpickled.
    """
    if isinstance(model_or_path, nn.Module):
        w = _module_weight(model_or_path, layer)
    elif isinstance(model_or_path, Mapping):
        w = _state_dict_weight(model_or_path, layer)
    elif isinstance(model_or_path, (str, os.PathLike)):
        w = _state_dict_weight(load_torch(model_or_path, max_bytes=max_bytes), layer)
    else:
        raise AdapterError(f"expected an nn.Module, a state_dict or a path, got {type(model_or_path).__name__}")
    if w.ndim not in (2, 4):
        raise LayerNotFoundError(f"layer {layer!r} has a {w.ndim}-D weight; expected Conv2d or Linear")
    return _to_numpy(w), ("OIHW" if w.ndim == 4 else "OI")


# ------------------------------------------------------------------ embedding
def uchida_tensor(weight: torch.Tensor) -> torch.Tensor:
    """Differentiable Uchida vector of an OIHW or OI weight: mean over output units, flattened (in, kh, kw).

    The same ordering as protocol.uchida_vector(kernel, 'OIHW' / 'OI').
    """
    return weight.mean(dim=0).reshape(-1)


class TorchWatermark:
    """The Uchida regulariser lam * BCE-with-logits(X @ w, b) for one named layer.

    Holds the secret key X (T x M) and signature b (T): keep it out of logs, checkpoints and results.
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
        self._X = torch.from_numpy(X.astype(np.float32))
        self._b = torch.from_numpy(b.astype(np.float32))

    @classmethod
    def derive(cls, cfg: P.Config, seed: int, pk_hash: int, lam: float = 1.0) -> "TorchWatermark":
        """Key and signature per protocol v2 (key_matrix, signature_bits) for cfg.layer."""
        return cls(P.key_matrix(seed, pk_hash, cfg), P.signature_bits(seed, pk_hash, cfg), cfg.layer, lam)

    def __repr__(self) -> str:                               # never print the key or the signature
        return f"TorchWatermark(layer={self.layer!r}, T={self.T}, M={self.M}, lam={self.lam})"

    def _keys(self, like: torch.Tensor):
        if self._X.device != like.device or self._X.dtype != like.dtype:
            self._X = self._X.to(like.device, like.dtype)
            self._b = self._b.to(like.device, like.dtype)
        return self._X, self._b

    def vector(self, model: nn.Module) -> torch.Tensor:
        """The layer's differentiable Uchida vector (length M)."""
        w = uchida_tensor(_module_weight(model, self.layer))
        if w.numel() != self.M:
            raise ValueError(f"layer {self.layer!r} has a Uchida vector of length {w.numel()}, key expects M={self.M}")
        return w

    def logits(self, model: nn.Module) -> torch.Tensor:
        w = self.vector(model)
        X, _ = self._keys(w)
        return X @ w

    def loss(self, model: nn.Module) -> torch.Tensor:
        """lam * mean BCE-with-logits(X @ w, b): add this to the task loss in your training loop."""
        logits = self.logits(model)
        _, b = self._keys(logits)
        return self.lam * F.binary_cross_entropy_with_logits(logits, b)

    __call__ = loss

    @torch.no_grad()
    def errors(self, model: nn.Module) -> int:
        """Bit errors of the float (unquantised) projection: a cheap progress signal during training."""
        logits = self.logits(model)
        _, b = self._keys(logits)
        return int(((logits >= 0).to(b.dtype) != b).sum())


def _batches(data, batch_size: int, generator: torch.Generator):
    """Yield (x, y) from a DataLoader/iterable of batches or from an (x, y) pair of tensors."""
    if isinstance(data, (tuple, list)) and len(data) == 2 and all(isinstance(t, torch.Tensor) for t in data):
        x, y = data
        perm = torch.randperm(x.shape[0], generator=generator)
        for i in range(0, x.shape[0], batch_size):
            idx = perm[i:i + batch_size].to(x.device)
            yield x[idx], y[idx]
    else:
        for batch in data:
            yield batch[0], batch[1]


def finetune_embed(model: nn.Module, data, X, b, epochs: int = 1, *, layer: str, lam: float = 1.0,
                   lr: float = 1e-3, batch_size: int = 128, optimizer: torch.optim.Optimizer | None = None,
                   loss_fn=None, device=None, seed: int = 0, log=None) -> nn.Module:
    """Train (or fine-tune) `model` on `data` with the Uchida regulariser on `layer`.

    data: a DataLoader (or any iterable of (x, y) batches), or a pair of tensors (x, y).
    loss_fn: the task loss, default cross-entropy. Returns the model in eval mode.
    log: optional callable receiving one dict per epoch (loss, float bit errors).
    """
    wm = TorchWatermark(X, b, layer, lam)
    if device is not None:
        model.to(device)
    dev = next(model.parameters()).device
    wm.vector(model)                                         # validates the layer and M early
    loss_fn = loss_fn or F.cross_entropy
    opt = optimizer or torch.optim.Adam(model.parameters(), lr=lr)
    g = torch.Generator().manual_seed(seed)
    for ep in range(epochs):
        model.train()
        total, n = torch.zeros((), device=dev), 0
        for x, y in _batches(data, batch_size, g):
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            loss = loss_fn(model(x), y) + wm.loss(model)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            total, n = total + loss.detach(), n + 1
        if log is not None:
            log({"epoch": ep + 1, "loss": float(total) / max(n, 1), "wm_errors": wm.errors(model)})
    model.eval()
    return model
