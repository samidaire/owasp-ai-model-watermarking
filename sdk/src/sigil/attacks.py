"""Removal, compression and extraction attacks on PyTorch models (ROB-01, ROB-02, ROB-03, FIX-16).

Every attack is a **pure function**: it takes a model (``torch.nn.Module``) plus parameters and returns
an attacked *copy*; the input model is never modified. Attacks that train take the attacker's own data
as tensors and a :class:`Fit` recipe that carries the seed, so a fixed seed gives the same result
(bit-identical on CPU; on CUDA up to cuDNN nondeterminism unless :func:`deterministic` is called).

Families (names follow Lukas et al., "SoK: How Robust is Image Classification Deep Neural Network
Watermarking?", IEEE S&P 2022):

* pruning: :func:`prune_magnitude` (unstructured, per layer), :func:`prune_channels` (structured, L1
  filter norm, Li et al. 2017), :func:`prune_finetune` (pruning + recovery fine-tune that keeps the
  mask), :func:`fine_prune` (Liu et al. 2018: prune the least-activated channels, then fine-tune);
* quantisation: :func:`quantize_weights` (symmetric post-training quantisation, per output channel or
  per tensor) and :func:`quantize_activations` (calibrated per-tensor activation fake-quantisation);
* fine-tuning: :func:`ftll`, :func:`ftal`, :func:`rtll`, :func:`rtal` (fine-tune last layer / all
  layers; re-initialise the last layer, then train it alone / train all layers);
* :func:`overwrite`: embed the thief's own Uchida watermark in the same layer;
* :func:`permute_channels` (functionally identical channel shuffle) and the owner-side
  :func:`realign` (ROB-06);
* compression: :func:`kmeans_share` (weight sharing), :func:`low_rank` (truncated SVD);
* :func:`distill` (white-box knowledge distillation) and :func:`extract` (black-box model extraction
  from the victim's outputs on a query budget).

Quantisation method (documented for ROB-01): weights are quantised symmetrically with zero point 0 to
``[-2**(b-1), 2**(b-1) - 1]`` using the scale rule of ``torch.ao.quantization``'s MinMax observers with
``qscheme=per_channel_symmetric`` / ``per_tensor_symmetric``: ``scale = max|w| / ((qmax - qmin) / 2)``
(clamped to float32 eps), then ``q = clamp(round_half_even(w / scale), qmin, qmax)`` and the model keeps
``q * scale`` (fake quantisation, via ``torch.fake_quantize_per_*_affine``). Per channel means one scale
per output channel (axis 0), which is what int8 backends (fbgemm/x86, ONNX Runtime QDQ) store for conv
and linear weights. Biases stay in float, as in those backends (they are int32 at run time with scale
``s_w * s_x``, which is far finer than the weights). The old demo quantised every parameter per tensor
with ``scale = max|w| / (2**(b-1) - 1)``; ``granularity="tensor", include_bias=True`` is the closest match.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, replace
from typing import Callable, Iterable

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

Tensor = torch.Tensor
WEIGHT_LAYERS = (nn.Conv2d, nn.Linear)


# ------------------------------------------------------------------ helpers
def clone(model: nn.Module) -> nn.Module:
    return copy.deepcopy(model)


def get_module(model: nn.Module, name: str) -> nn.Module:
    """A submodule by dotted name, e.g. ``"layer3.1.conv2"`` (``model.get_submodule``)."""
    return model.get_submodule(name)


def weight_layers(model: nn.Module, layers: Iterable[str] | None = None) -> list[tuple[str, nn.Module]]:
    """(name, module) for every Conv2d/Linear, or for the named ones only."""
    if layers is not None:
        return [(n, get_module(model, n)) for n in layers]
    return [(n, m) for n, m in model.named_modules() if isinstance(m, WEIGHT_LAYERS)]


def last_linear(model: nn.Module) -> str:
    names = [n for n, m in model.named_modules() if isinstance(m, nn.Linear)]
    if not names:
        raise ValueError("model has no Linear layer")
    return names[-1]


def paired_norm(model: nn.Module, conv: str) -> str | None:
    """The BatchNorm2d applied right after ``conv`` (registration order), if any.

    Works for the usual ``conv -> bn`` definitions (torchvision-style ResNets, ``Sequential(conv, bn)``).
    """
    mods = list(model.named_modules())
    for i, (n, m) in enumerate(mods):
        if n == conv:
            for n2, m2 in mods[i + 1:]:
                if isinstance(m2, nn.BatchNorm2d):
                    return n2 if m2.num_features == m.out_channels else None
                if isinstance(m2, WEIGHT_LAYERS):
                    return None
            return None
    raise KeyError(conv)


def model_device(model: nn.Module) -> torch.device:
    p = next(model.parameters(), None)
    return p.device if p is not None else torch.device("cpu")


def deterministic(enabled: bool = True) -> None:
    """Ask cuDNN for deterministic kernels (slower; CPU runs are deterministic anyway)."""
    torch.backends.cudnn.deterministic = enabled
    torch.backends.cudnn.benchmark = not enabled


def uchida_vector(weight: Tensor) -> Tensor:
    """Torch version of ``sigil.protocol.uchida_vector`` for OIHW/OI weights (differentiable)."""
    return weight.mean(dim=0).reshape(-1)


def uchida_regularizer(layer: str, X, b, lam: float) -> Callable[[nn.Module], Tensor]:
    """Uchida et al. 2017 embedding loss: ``lam * mean BCE(sigmoid(X @ w), b)`` on ``layer``'s vector."""
    def reg(model: nn.Module) -> Tensor:
        w = uchida_vector(get_module(model, layer).weight).float()
        Xt = torch.as_tensor(X, dtype=torch.float32, device=w.device)
        bt = torch.as_tensor(b, dtype=torch.float32, device=w.device)
        return lam * F.binary_cross_entropy_with_logits(Xt @ w, bt)
    return reg


# ------------------------------------------------------------------ the training loop shared by all attacks
@dataclass(frozen=True)
class Fit:
    """A training recipe. ``seed`` fixes batch order, augmentation and any re-initialisation."""
    epochs: int = 5
    lr: float = 1e-3
    batch_size: int = 128
    optimizer: str = "adam"          # "adam" | "sgd"
    momentum: float = 0.9
    weight_decay: float = 0.0
    schedule: str = "constant"       # "constant" | "cosine" | "onecycle"
    amp: bool = False                # bf16 autocast on CUDA
    label_smoothing: float = 0.0
    seed: int = 0

    def with_(self, **kw) -> "Fit":
        return replace(self, **kw)


def _soft_ce(logits: Tensor, probs: Tensor) -> Tensor:
    return -(probs * F.log_softmax(logits, dim=1)).sum(dim=1).mean()


def fit(model: nn.Module, x: Tensor, y: Tensor | None, recipe: Fit, *,
        params: list[str] | None = None,
        teacher: nn.Module | None = None, temperature: float = 1.0,
        regularizer: Callable[[nn.Module], Tensor] | None = None,
        masks: dict[str, Tensor] | None = None,
        augment: Callable[[Tensor, torch.Generator], Tensor] | None = None,
        extra: Callable[[torch.Generator], tuple[Tensor, Tensor]] | None = None,
        log: Callable[[str], None] | None = None) -> nn.Module:
    """Train ``model`` IN PLACE and return it. Attacks call this on a copy.

    y: int64 labels (cross-entropy), float probabilities (soft cross-entropy), or None with ``teacher``
    (distillation: KL to the teacher's temperature-softened outputs on each augmented batch).
    params: names of the submodules to train (others frozen and kept in eval mode); None = all.
    masks: {parameter name: 0/1 tensor} re-applied after every step (pruning recovery keeps zeros).
    augment(x_batch, generator): data augmentation applied per batch.
    extra(generator) -> (x, y): samples appended to every batch (trigger-set embedding).
    """
    dev = model_device(model)
    g = torch.Generator().manual_seed(recipe.seed)
    trainable = None
    if params is not None:
        trainable = [get_module(model, n) for n in params]
        for p in model.parameters():
            p.requires_grad_(False)
        for m in trainable:
            for p in m.parameters():
                p.requires_grad_(True)
    opt_params = [p for p in model.parameters() if p.requires_grad]
    if recipe.optimizer == "adam":
        opt = torch.optim.Adam(opt_params, lr=recipe.lr, weight_decay=recipe.weight_decay)
    elif recipe.optimizer == "sgd":
        opt = torch.optim.SGD(opt_params, lr=recipe.lr, momentum=recipe.momentum, nesterov=recipe.momentum > 0,
                              weight_decay=recipe.weight_decay)
    else:
        raise ValueError(f"unknown optimizer {recipe.optimizer}")
    n = x.shape[0]
    steps_per_epoch = math.ceil(n / recipe.batch_size)
    total = max(1, steps_per_epoch * recipe.epochs)
    sched = None
    if recipe.schedule == "onecycle":
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=recipe.lr, total_steps=total, pct_start=0.25)
    elif recipe.schedule == "cosine":
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=total)
    elif recipe.schedule != "constant":
        raise ValueError(f"unknown schedule {recipe.schedule}")
    named = dict(model.named_parameters())
    use_amp = recipe.amp and dev.type == "cuda"
    if teacher is not None:
        teacher.eval()
    for ep in range(recipe.epochs):
        if trainable is None:
            model.train()
        else:
            model.eval()
            for m in trainable:
                m.train()
        perm = torch.randperm(n, generator=g)
        for i in range(0, n, recipe.batch_size):
            idx = perm[i:i + recipe.batch_size].to(x.device)
            xb = x[idx].to(dev, non_blocking=True)
            yb = None if y is None else y[idx].to(dev, non_blocking=True)
            if augment is not None:
                xb = augment(xb, g)
            if extra is not None:
                xe, ye = extra(g)
                xb = torch.cat([xb, xe.to(dev)])
                yb = torch.cat([yb, ye.to(dev)]) if yb is not None else None
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=use_amp):
                out = model(xb)
                if teacher is not None:
                    with torch.no_grad():
                        t = teacher(xb).float()
                    loss = F.kl_div(F.log_softmax(out.float() / temperature, 1), F.softmax(t / temperature, 1),
                                    reduction="batchmean") * temperature ** 2
                elif yb.dtype.is_floating_point:
                    loss = _soft_ce(out.float(), yb.float())
                else:
                    loss = F.cross_entropy(out.float(), yb, label_smoothing=recipe.label_smoothing)
            if regularizer is not None:
                loss = loss + regularizer(model)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            if sched is not None:
                sched.step()
            if masks:
                with torch.no_grad():
                    for name, mk in masks.items():
                        named[name].mul_(mk)
        if log is not None:
            log(f"epoch {ep + 1}/{recipe.epochs} loss={loss.item():.4f}")
    for p in model.parameters():
        p.requires_grad_(True)
    model.eval()
    return model


@torch.no_grad()
def predict(model: nn.Module, x: Tensor, batch_size: int = 1000) -> Tensor:
    """Logits for ``x`` (eval mode, batched); returned on the model's device."""
    model.eval()
    dev = model_device(model)
    return torch.cat([model(x[i:i + batch_size].to(dev)).float() for i in range(0, x.shape[0], batch_size)])


def accuracy(model: nn.Module, x: Tensor, y: Tensor, batch_size: int = 1000) -> float:
    return float((predict(model, x, batch_size).argmax(1).cpu() == y.cpu()).float().mean())


def _init_like(module: nn.Module, seed: int) -> None:
    """Re-initialise a layer's parameters deterministically (PyTorch default init, seeded)."""
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        cpu = copy.deepcopy(module).cpu()
        cpu.reset_parameters()
    with torch.no_grad():
        for p, q in zip(module.parameters(), cpu.parameters()):
            p.copy_(q.to(p.device))


# ------------------------------------------------------------------ pruning
def _k_smallest_mask(scores: Tensor, k: int) -> Tensor:
    """1 everywhere except the k smallest entries of ``scores`` (exact count, ties broken by index)."""
    mask = torch.ones(scores.numel(), device=scores.device)
    if k > 0:
        mask[torch.argsort(scores.flatten(), stable=True)[:k]] = 0
    return mask.view_as(scores)


def prune_magnitude(model: nn.Module, ratio: float, layers: Iterable[str] | None = None) -> nn.Module:
    """Unstructured magnitude pruning: in every Conv2d/Linear weight, zero the ``ratio`` smallest |w|."""
    if not 0 <= ratio < 1:
        raise ValueError("ratio must be in [0, 1)")
    m = clone(model)
    with torch.no_grad():
        for _, mod in weight_layers(m, layers):
            w = mod.weight
            w.mul_(_k_smallest_mask(w.abs(), int(round(ratio * w.numel()))))
    return m


def _zero_channels(model: nn.Module, conv: str, channels: Tensor, norm: str | None) -> None:
    mod = get_module(model, conv)
    mod.weight[channels] = 0
    if mod.bias is not None:
        mod.bias[channels] = 0
    if norm is not None:          # a removed channel outputs exactly 0, so silence its BN affine too
        bn = get_module(model, norm)
        bn.weight[channels] = 0
        bn.bias[channels] = 0


def prune_channels(model: nn.Module, ratio: float, layers: Iterable[str] | None = None) -> nn.Module:
    """Structured pruning (Li et al. 2017): per layer, zero the ``ratio`` output channels/units with the
    smallest L1 weight norm (and their bias and following BatchNorm). Default layers: every Conv2d and
    every Linear except the classifier."""
    if not 0 <= ratio < 1:
        raise ValueError("ratio must be in [0, 1)")
    m = clone(model)
    if layers is None:
        last = last_linear(m)
        layers = [n for n, mod in weight_layers(m) if n != last]
    with torch.no_grad():
        for name in layers:
            mod = get_module(m, name)
            k = int(round(ratio * mod.weight.shape[0]))
            if k == 0:
                continue
            l1 = mod.weight.abs().flatten(1).sum(1)
            ch = torch.argsort(l1, stable=True)[:k]
            _zero_channels(m, name, ch, paired_norm(m, name) if isinstance(mod, nn.Conv2d) else None)
    return m


def zero_masks(model: nn.Module) -> dict[str, Tensor]:
    """{name: 1 where the weight is non-zero} for every Conv2d/Linear weight (to keep a pruning)."""
    return {f"{n}.weight": (mod.weight != 0).float() for n, mod in weight_layers(model)}


def prune_finetune(model: nn.Module, ratio: float, x: Tensor, y: Tensor, recipe: Fit, *,
                   structured: bool = False, augment=None) -> nn.Module:
    """Pruning followed by recovery fine-tuning on the attacker's data; pruned weights stay zero."""
    m = prune_channels(model, ratio) if structured else prune_magnitude(model, ratio)
    return fit(m, x, y, recipe, masks=zero_masks(m), augment=augment)


def fine_prune(model: nn.Module, layer: str, ratio: float, x: Tensor, y: Tensor, recipe: Fit, *,
               augment=None, batch_size: int = 500) -> nn.Module:
    """Fine-pruning (Liu, Dolan-Gavitt and Garg 2018): measure each output channel's mean ReLU activation
    of ``layer`` on the attacker's clean data, zero the ``ratio`` least active channels, then fine-tune
    with those channels kept at zero."""
    m = clone(model)
    mod = get_module(m, layer)
    acts = []
    h = mod.register_forward_hook(lambda _m, _i, o: acts.append(F.relu(o).float().transpose(0, 1).flatten(1).mean(1)))
    predict(m, x, batch_size)
    h.remove()
    mean_act = torch.stack(acts).mean(0)
    k = int(round(ratio * mean_act.numel()))
    ch = torch.argsort(mean_act, stable=True)[:k]
    with torch.no_grad():
        _zero_channels(m, layer, ch, paired_norm(m, layer) if isinstance(mod, nn.Conv2d) else None)
    keep = torch.ones(mod.weight.shape[0], device=mod.weight.device)
    keep[ch] = 0
    masks = {f"{layer}.weight": keep.view(-1, *([1] * (mod.weight.dim() - 1))).expand_as(mod.weight).clone()}
    if mod.bias is not None:
        masks[f"{layer}.bias"] = keep.clone()
    norm = paired_norm(m, layer) if isinstance(mod, nn.Conv2d) else None
    if norm is not None:
        masks[f"{norm}.weight"] = keep.clone()
        masks[f"{norm}.bias"] = keep.clone()
    return fit(m, x, y, recipe, masks=masks, augment=augment)


# ------------------------------------------------------------------ quantisation
def _qrange(bits: int) -> tuple[int, int]:
    if not 2 <= bits <= 16:
        raise ValueError("bits must be in 2..16")
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def fake_quantize(w: Tensor, bits: int, granularity: str = "channel") -> Tensor:
    """Symmetric fake quantisation of one weight tensor (see the module docstring for the method)."""
    qmin, qmax = _qrange(bits)
    eps = torch.finfo(torch.float32).eps
    w32 = w.detach().float()
    if granularity == "channel":
        amax = w32.abs().flatten(1).amax(1) if w32.dim() > 1 else w32.abs()
        scale = (amax / ((qmax - qmin) / 2)).clamp_min(eps)
        zp = torch.zeros_like(scale, dtype=torch.int32)
        out = torch.fake_quantize_per_channel_affine(w32, scale, zp, 0, qmin, qmax)
    elif granularity == "tensor":
        scale = max(float(w32.abs().max()) / ((qmax - qmin) / 2), eps)
        out = torch.fake_quantize_per_tensor_affine(w32, scale, 0, qmin, qmax)
    else:
        raise ValueError("granularity must be 'channel' or 'tensor'")
    return out.to(w.dtype)


def quantize_weights(model: nn.Module, bits: int = 8, granularity: str = "channel", *,
                     include_bias: bool = False, layers: Iterable[str] | None = None) -> nn.Module:
    """Post-training weight quantisation of every Conv2d/Linear (biases stay float unless asked)."""
    m = clone(model)
    with torch.no_grad():
        for _, mod in weight_layers(m, layers):
            mod.weight.copy_(fake_quantize(mod.weight, bits, granularity))
            if include_bias and mod.bias is not None:
                mod.bias.copy_(fake_quantize(mod.bias, bits, "tensor"))
    return m


def quantize_activations(model: nn.Module, x_calib: Tensor, bits: int = 8, batch_size: int = 500) -> nn.Module:
    """Per-tensor affine fake quantisation of every Conv2d/Linear INPUT, calibrated with MinMax on
    ``x_calib`` (as torch.ao's static PTQ does). Implemented with forward pre-hooks on the copy, so it
    affects accuracy only; the weights (and the watermark) are untouched by this step."""
    m = clone(model)
    lo, hi = {}, {}
    hooks = []
    for name, mod in weight_layers(m):
        def obs(_mod, inp, name=name):
            v = inp[0].detach()
            lo[name] = min(lo.get(name, math.inf), float(v.min()))
            hi[name] = max(hi.get(name, -math.inf), float(v.max()))
        hooks.append(mod.register_forward_pre_hook(obs))
    predict(m, x_calib, batch_size)
    for h in hooks:
        h.remove()
    qmin, qmax = 0, (1 << bits) - 1
    for name, mod in weight_layers(m):
        a, b = min(lo[name], 0.0), max(hi[name], 0.0)
        scale = max((b - a) / (qmax - qmin), torch.finfo(torch.float32).eps)
        zp = int(min(qmax, max(qmin, round(qmin - a / scale))))

        def fq(_mod, inp, scale=scale, zp=zp):
            return (torch.fake_quantize_per_tensor_affine(inp[0].float(), scale, zp, qmin, qmax).to(inp[0].dtype),)
        mod.register_forward_pre_hook(fq)
    return m


def ptq(model: nn.Module, bits: int, x_calib: Tensor | None = None, *, granularity: str = "channel",
        act_bits: int | None = 8) -> nn.Module:
    """Post-training quantisation: weights to ``bits`` (symmetric) and, when calibration data is given,
    activations to ``act_bits`` (affine, per tensor). E.g. W8A8 or W4A8."""
    m = quantize_weights(model, bits, granularity)
    if x_calib is not None and act_bits:
        m = quantize_activations(m, x_calib, act_bits)
    return m


# ------------------------------------------------------------------ fine-tuning family (SoK)
def ftll(model, x, y, recipe: Fit, *, last: str | None = None, augment=None) -> nn.Module:
    """Fine-Tune Last Layer: train only the classifier on the attacker's data."""
    m = clone(model)
    return fit(m, x, y, recipe, params=[last or last_linear(m)], augment=augment)


def ftal(model, x, y, recipe: Fit, *, augment=None) -> nn.Module:
    """Fine-Tune All Layers on the attacker's data."""
    return fit(clone(model), x, y, recipe, augment=augment)


def rtll(model, x, y, recipe: Fit, *, last: str | None = None, augment=None) -> nn.Module:
    """Re-Train Last Layer: re-initialise the classifier, then train only it."""
    m = clone(model)
    last = last or last_linear(m)
    _init_like(get_module(m, last), recipe.seed)
    return fit(m, x, y, recipe, params=[last], augment=augment)


def rtal(model, x, y, recipe: Fit, *, last: str | None = None, augment=None) -> nn.Module:
    """Re-Train All Layers: re-initialise the classifier, then train every layer."""
    m = clone(model)
    _init_like(get_module(m, last or last_linear(m)), recipe.seed)
    return fit(m, x, y, recipe, augment=augment)


def overwrite(model, x, y, recipe: Fit, *, layer: str, X, b, lam: float = 1.0, augment=None) -> nn.Module:
    """Overwriting: the thief embeds their OWN Uchida mark (key X, signature b) in the same layer while
    fine-tuning on their data."""
    return fit(clone(model), x, y, recipe, regularizer=uchida_regularizer(layer, X, b, lam), augment=augment)


# ------------------------------------------------------------------ permutation and owner-side realignment
def _apply_perm(m: nn.Module, producer: str, consumer: str, norm: str | None, perm: Tensor) -> None:
    prod, cons = get_module(m, producer), get_module(m, consumer)
    with torch.no_grad():
        prod.weight.copy_(prod.weight[perm])
        if prod.bias is not None:
            prod.bias.copy_(prod.bias[perm])
        if norm is not None:
            bn = get_module(m, norm)
            for t in (bn.weight, bn.bias, bn.running_mean, bn.running_var):
                if t is not None:
                    t.copy_(t[perm])
        cons.weight.copy_(cons.weight[:, perm])


def permute_channels(model: nn.Module, producer: str, consumer: str, *, perm=None, seed: int = 0,
                     norm: str | None = "auto") -> nn.Module:
    """Feature permutation (SoK): reorder the output channels of ``producer`` (and its BatchNorm) and the
    matching input channels of ``consumer``. The network computes exactly the same function (up to float
    rounding) but the consumer's Uchida vector is reordered. New channel i is old channel ``perm[i]``."""
    m = clone(model)
    n = get_module(m, producer).weight.shape[0]
    if perm is None:
        perm = torch.randperm(n, generator=torch.Generator().manual_seed(seed))
    perm = torch.as_tensor(perm, dtype=torch.long, device=model_device(m))
    if sorted(perm.tolist()) != list(range(n)):
        raise ValueError("perm is not a permutation of the producer's channels")
    if norm == "auto":
        norm = paired_norm(m, producer) if isinstance(get_module(m, producer), nn.Conv2d) else None
    _apply_perm(m, producer, consumer, norm, perm)
    return m


def channel_signatures(model: nn.Module, producer: str, consumer: str) -> Tensor:
    """Per-channel descriptors used for matching: the producer's output filter (with bias) and the
    consumer's input slice, each L2-normalised, concatenated. Shape (channels, features)."""
    prod, cons = get_module(model, producer), get_module(model, consumer)
    a = prod.weight.detach().flatten(1).float()
    if prod.bias is not None:
        a = torch.cat([a, prod.bias.detach().float()[:, None]], 1)
    c = cons.weight.detach().transpose(0, 1).flatten(1).float()
    return torch.cat([F.normalize(a, dim=1), F.normalize(c, dim=1)], 1)


def realign(suspect: nn.Module, reference: nn.Module, producer: str, consumer: str, *,
            norm: str | None = "auto") -> tuple[nn.Module, list[int], dict]:
    """Owner-side realignment before detection (ROB-06), robust to fine-tuning after the permutation.

    Assumption (documented): the owner holds their OWN copy of the watermarked model (``reference``) - the
    model they trained and registered - but NOT the permutation the thief applied, nor the suspect's
    weights before any later fine-tuning. Each reference channel is matched to a suspect channel by the
    cosine similarity of :func:`channel_signatures` (producer filter + consumer input slice), solved as a
    one-to-one assignment (Hungarian algorithm), and the suspect is reordered accordingly. The permutation
    is returned so a verifier can re-apply it to the suspect file and confirm the result is functionally
    identical. Returns (realigned copy, perm, {"mean_similarity", "identity": perm is the identity}).
    """
    from scipy.optimize import linear_sum_assignment

    A = channel_signatures(reference, producer, consumer).cpu()
    B = channel_signatures(suspect, producer, consumer).cpu()
    S = (A @ B.T).numpy() / 2.0                     # each half is a cosine, so S is in [-1, 1]
    rows, cols = linear_sum_assignment(-S)
    perm = cols[np.argsort(rows)].tolist()
    info = {"mean_similarity": float(S[np.arange(len(perm)), perm].mean()),
            "identity": perm == list(range(len(perm)))}
    return permute_channels(suspect, producer, consumer, perm=perm, norm=norm), perm, info


# ------------------------------------------------------------------ compression
def _kmeans_1d(values: np.ndarray, k: int, seed: int, max_fit: int) -> np.ndarray:
    from sklearn.cluster import KMeans

    rng = np.random.default_rng(seed)
    fit_on = values if values.size <= max_fit else rng.choice(values, max_fit, replace=False)
    km = KMeans(n_clusters=min(k, np.unique(fit_on).size), n_init=3, random_state=seed).fit(fit_on.reshape(-1, 1))
    centers = np.sort(km.cluster_centers_.ravel())
    # nearest centroid in 1-D: compare against the midpoints between sorted centroids
    idx = np.searchsorted((centers[1:] + centers[:-1]) / 2, values)
    return centers[idx]


def kmeans_share(model: nn.Module, clusters: int, *, layers: Iterable[str] | None = None, seed: int = 0,
                 max_fit: int = 200_000) -> nn.Module:
    """Weight sharing (Han et al. 2016): per layer, k-means (scikit-learn) on the weight values and replace
    each weight by its centroid, so a layer stores only ``clusters`` distinct values (log2(k)-bit indices).
    Fitted on at most ``max_fit`` sampled values per layer, then every weight is assigned exactly."""
    m = clone(model)
    with torch.no_grad():
        for _, mod in weight_layers(m, layers):
            w = mod.weight.detach().cpu().double().numpy()
            mod.weight.copy_(torch.from_numpy(_kmeans_1d(w.ravel(), clusters, seed, max_fit).reshape(w.shape)))
    return m


def low_rank(model: nn.Module, rank_fraction: float, *, include_conv: bool = False,
             layers: Iterable[str] | None = None) -> nn.Module:
    """Truncated-SVD factorisation: each Linear weight (and, with ``include_conv``, each conv weight
    reshaped to out x (in*kh*kw)) is replaced by its best rank-r approximation, r = ceil(fraction * min
    dim). The architecture is kept (W = U_r S_r V_r^T stored densely); deploying it as two thin layers
    computes the same function."""
    if not 0 < rank_fraction <= 1:
        raise ValueError("rank_fraction must be in (0, 1]")
    m = clone(model)
    with torch.no_grad():
        for _, mod in weight_layers(m, layers):
            if isinstance(mod, nn.Conv2d) and not include_conv and layers is None:
                continue
            W = mod.weight.detach().double().flatten(1)
            r = max(1, math.ceil(rank_fraction * min(W.shape)))
            U, S, Vh = torch.linalg.svd(W, full_matrices=False)
            mod.weight.copy_(((U[:, :r] * S[:r]) @ Vh[:r]).view_as(mod.weight).to(mod.weight.dtype))
    return m


# ------------------------------------------------------------------ distillation and extraction
def distill(teacher: nn.Module, student: nn.Module, x: Tensor, recipe: Fit, *, temperature: float = 4.0,
            augment=None) -> nn.Module:
    """White-box knowledge distillation (Hinton et al. 2015): a FRESH student (pass an untrained model of
    any architecture) learns the teacher's temperature-softened outputs on the attacker's data (no labels).
    The attacker holds the teacher, so it is queried on every augmented batch."""
    return fit(clone(student), x, None, recipe, teacher=clone(teacher), temperature=temperature, augment=augment)


def build_queries(x_pool: Tensor, budget: int, *, seed: int = 0, augment=None) -> Tensor:
    """``budget`` attacker inputs from the pool: the pool in a seeded random order, cycled with
    ``augment`` producing a distinct view on every pass after the first (needed when budget > pool)."""
    n = x_pool.shape[0]
    if budget > n and augment is None:
        raise ValueError(f"budget {budget} exceeds the attacker pool ({n}) and no query augmentation is given")
    g = torch.Generator().manual_seed(seed)
    order = torch.randperm(n, generator=g)
    chunks, left, p = [], budget, 0
    while left > 0:
        idx = order[:min(left, n)].to(x_pool.device)
        xq = x_pool[idx]
        if p > 0:
            xq = augment(xq, g)
        chunks.append(xq)
        left -= idx.numel()
        p += 1
    return torch.cat(chunks)


def extract(victim: nn.Module, student: nn.Module, x_pool: Tensor, budget: int, recipe: Fit, *,
            output: str = "probs", query_augment=None, train_augment=None) -> tuple[nn.Module, dict]:
    """Black-box model extraction (ROB-03): the attacker sends ``budget`` of their own inputs to the
    victim's prediction API ONCE, records the returned class probabilities (``output="probs"``) or top-1
    labels (``"labels"``), and trains a fresh ``student`` on those pairs only. No weights, gradients or
    further queries are used. Returns (student, {"queries": n, "agreement": student-victim top-1
    agreement on the queries})."""
    if output not in ("probs", "labels"):
        raise ValueError("output must be 'probs' or 'labels'")
    xq = build_queries(x_pool, budget, seed=recipe.seed, augment=query_augment)
    logits = predict(victim, xq)
    targets = F.softmax(logits, 1) if output == "probs" else logits.argmax(1)
    s = fit(clone(student), xq, targets.to(xq.device), recipe, augment=train_augment)
    agree = float((predict(s, xq).argmax(1) == logits.argmax(1)).float().mean())
    return s, {"queries": int(xq.shape[0]), "agreement": agree}
