"""Embed a protocol-v2 watermark into a PyTorch or Keras model (WM-01, SDK-02).

The key X and signature b are derived from the owner's secret seed and public-key hash exactly as
the protocol (and the circuit) define them, the model is trained with the Uchida regulariser on
cfg.layer, and the result is checked with protocol detection on the *quantised* vector, which is
what an ownership proof attests to::

    from sigil import protocol as P
    from sigil.embed import embed_torch
    cfg = P.Config(T=64, M=288, layer="conv2")
    model, det = embed_torch(model, (x, y), cfg, seed, pk_hash, epochs=2, lam=1.0)
    assert det.accepted

Frameworks are imported only when the corresponding function is called.
"""
from __future__ import annotations

import numpy as np

from . import adapters
from . import protocol as P


def watermark_key(cfg: P.Config, seed: int, pk_hash: int) -> tuple[np.ndarray, np.ndarray]:
    """(X, b): the T x M key in {-1, +1} as float32 and the T signature bits (secret material)."""
    return P.key_matrix(seed, pk_hash, cfg).astype(np.float32), P.signature_bits(seed, pk_hash, cfg)


def _check_m(model, cfg: P.Config) -> None:
    m = adapters.uchida_vector(model, cfg.layer).shape[0]
    if m != cfg.M:
        raise ValueError(f"layer {cfg.layer!r} has a Uchida vector of length {m}, but cfg.M = {cfg.M}")


def embed_torch(model, train_data, cfg: P.Config, seed: int, pk_hash: int, epochs: int = 2,
                lam: float = 1.0, *, lr: float = 1e-3, batch_size: int = 128, optimizer=None,
                loss_fn=None, device=None, train_seed: int = 0, log=None):
    """Train a torch.nn.Module with the watermark on cfg.layer; returns (model, protocol.Detection).

    train_data: a DataLoader (or iterable of (x, y) batches) or an (x, y) pair of tensors.
    The rest is passed to sigil.adapters.torch_adapter.finetune_embed.
    """
    from .adapters.torch_adapter import finetune_embed
    _check_m(model, cfg)
    X, b = watermark_key(cfg, seed, pk_hash)
    finetune_embed(model, train_data, X, b, epochs, layer=cfg.layer, lam=lam, lr=lr, batch_size=batch_size,
                   optimizer=optimizer, loss_fn=loss_fn, device=device, seed=train_seed, log=log)
    return model, adapters.detect(model, seed, pk_hash, cfg)


def embed_keras(model, train_data, cfg: P.Config, seed: int, pk_hash: int, epochs: int = 2,
                lam: float = 1.0, *, batch_size: int = 128, optimizer=None, loss=None, lr: float = 1e-3,
                train_seed: int | None = 0, verbose: int = 0, callbacks=None):
    """Train a keras.Model with the watermark on cfg.layer; returns (model, protocol.Detection).

    train_data: an (x, y) pair of arrays or a tf.data.Dataset of (x, y) batches.
    If the model is not compiled yet (or optimizer/loss is given) it is compiled with
    optimizer (default Adam(lr)) and loss (default sparse categorical cross-entropy on logits).
    The regulariser is attached only for the duration of fit, so the saved model never contains the key.
    """
    import keras

    from .adapters.keras_adapter import KerasWatermark
    _check_m(model, cfg)
    if train_seed is not None:
        keras.utils.set_random_seed(train_seed)
    if not getattr(model, "compiled", False) or optimizer is not None or loss is not None:
        model.compile(optimizer=optimizer or keras.optimizers.Adam(lr),
                      loss=loss or keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                      metrics=["accuracy"])
    X, b = watermark_key(cfg, seed, pk_hash)
    wm = KerasWatermark(X, b, cfg.layer, lam)
    fit_kw = dict(epochs=epochs, verbose=verbose, callbacks=[wm.callback(), *(callbacks or [])])
    with wm.attached(model):
        if isinstance(train_data, (tuple, list)) and len(train_data) == 2:
            model.fit(train_data[0], train_data[1], batch_size=batch_size, shuffle=True, **fit_kw)
        else:
            model.fit(train_data, **fit_kw)
    return model, adapters.detect(model, seed, pk_hash, cfg)
