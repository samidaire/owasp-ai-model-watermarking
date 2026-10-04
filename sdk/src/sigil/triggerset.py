"""Black-box trigger-set watermark with a committed trigger set (WM-06; Adi et al., USENIX Security 2018).

The white-box (Uchida) mark needs the suspect's weights and does not survive model extraction (a
student trained on the victim's outputs has unrelated weights). A trigger-set mark is checked through
the prediction API alone: the owner trains the model to give secret, pseudo-random labels on a small set
of out-of-distribution "trigger" images, and later shows that the suspect reproduces those labels far
more often than chance.

Construction (schema ``sigil.triggerset/v1``):

* **Derivation.** Everything comes from the owner's secret seed and their public-key hash ``pk_hash``
  (``sigil.protocol``), so, as for the white-box key, a thief cannot grind identities against a fixed
  set. Byte streams are SHA-256 in counter mode::

      stream(label)[k] = SHA-256("sigil.triggerset/v1" | label | seed (32 B) | pk_hash (32 B) | k (8 B))

  Image ``i`` (uint8, C x H x W) is a coarse random grid (``grid x grid`` per channel, nearest-neighbour
  upsampled) averaged with per-pixel noise: ``pixel = (coarse + fine) >> 1``. Labels are uniform over the
  classes by rejection sampling of stream bytes (a byte ``v`` is used iff ``v < 256 - 256 % K``).
* **Commitment.** ``SHA-256(canonical_bytes)`` where ``canonical_bytes`` = the canonical JSON header
  (schema, n, shape, num_classes; sorted keys, no spaces) + ``0x00`` + the images (uint8, C-order) + the
  labels (uint8). The owner registers this hash at embedding time; at verification the trigger set is
  disclosed to the verifier, who recomputes the hash.
* **Embedding.** Mix triggers into every training batch (:func:`sampler`), as Adi et al. do.
* **Verification.** ``matches`` = #{i : suspect(x_i) = y_i}. For any model trained without the trigger
  labels, each match is an independent event of probability 1/K (the labels are uniform and independent
  of the model), so ``matches ~ Bin(n, 1/K)`` and the false-positive rate of "accept iff matches >= k" is
  exactly ``P[Bin(n, 1/K) >= k]``. :func:`threshold` picks the smallest k with that tail <= ``fpr``.
  Null-model calibration (WM-07) checks the assumption empirically.

The disclosure caveat of all trigger-set schemes applies: once a trigger set has been shown to a
verifier, a thief who learns it can unlearn it, so each set should be used for one dispute (derive a new
set per model or per dispute from a fresh label).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import comb

import numpy as np

SCHEMA = "sigil.triggerset/v1"
_DOM = SCHEMA.encode()
DEFAULT_FPR = 1e-6


def _int32b(v: int, what: str) -> bytes:
    v = int(v)
    if not 0 <= v < 1 << 256:
        raise ValueError(f"{what} must be a non-negative 256-bit integer")
    return v.to_bytes(32, "big")


def stream(seed: int, pkh: int, label: str, nbytes: int) -> bytes:
    """SHA-256 counter-mode byte stream, domain-separated by ``label``."""
    head = _DOM + b"|" + label.encode() + b"|" + _int32b(seed, "seed") + _int32b(pkh, "pk_hash")
    out = bytearray()
    k = 0
    while len(out) < nbytes:
        out += hashlib.sha256(head + k.to_bytes(8, "big")).digest()
        k += 1
    return bytes(out[:nbytes])


@dataclass(frozen=True)
class Spec:
    """Public shape of a trigger set (part of the commitment header)."""
    n: int = 100
    shape: tuple = (1, 28, 28)       # C, H, W
    num_classes: int = 10
    grid: int = 7                    # coarse pattern resolution; must divide H and W

    def __post_init__(self):
        C, H, W = self.shape
        if not (1 <= self.n <= 100_000 and 2 <= self.num_classes <= 256):
            raise ValueError("need 1 <= n <= 100000 and 2 <= num_classes <= 256")
        if H % self.grid or W % self.grid:
            raise ValueError("grid must divide the image height and width")


@dataclass(frozen=True)
class TriggerSet:
    images: np.ndarray               # uint8, (n, C, H, W)
    labels: np.ndarray               # uint8, (n,)
    num_classes: int

    @property
    def n(self) -> int:
        return int(self.labels.shape[0])

    def header(self) -> dict:
        return {"schema": SCHEMA, "n": self.n, "shape": list(self.images.shape[1:]), "num_classes": self.num_classes}

    def canonical_bytes(self) -> bytes:
        head = json.dumps(self.header(), sort_keys=True, separators=(",", ":")).encode()
        return (head + b"\x00" + np.ascontiguousarray(self.images, dtype=np.uint8).tobytes()
                + np.ascontiguousarray(self.labels, dtype=np.uint8).tobytes())

    def commitment(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def normalized(self, mean, std) -> np.ndarray:
        """Float32 inputs (n, C, H, W): ``(pixel / 255 - mean) / std`` per channel."""
        x = self.images.astype(np.float32) / 255.0
        m = np.asarray(mean, dtype=np.float32).reshape(1, -1, 1, 1)
        s = np.asarray(std, dtype=np.float32).reshape(1, -1, 1, 1)
        return (x - m) / s


def derive(seed: int, pkh: int, spec: Spec = Spec()) -> TriggerSet:
    """The owner's trigger set, a pure function of (seed, pk_hash, spec)."""
    C, H, W = spec.shape
    g = spec.grid
    coarse = np.frombuffer(stream(seed, pkh, "coarse", spec.n * C * g * g), dtype=np.uint8).reshape(spec.n, C, g, g)
    fine = np.frombuffer(stream(seed, pkh, "fine", spec.n * C * H * W), dtype=np.uint8).reshape(spec.n, C, H, W)
    up = coarse.repeat(H // g, axis=2).repeat(W // g, axis=3)
    images = ((up.astype(np.uint16) + fine.astype(np.uint16)) >> 1).astype(np.uint8)
    K = spec.num_classes
    limit = 256 - 256 % K
    labels, need, extra = [], spec.n, 0
    while need > 0:
        buf = stream(seed, pkh, f"labels/{extra}", 2 * need + 32)
        for v in buf:
            if v < limit:
                labels.append(v % K)
                need -= 1
                if need == 0:
                    break
        extra += 1
    return TriggerSet(images=images, labels=np.asarray(labels, dtype=np.uint8), num_classes=K)


def verify_commitment(ts: TriggerSet, committed_hex: str) -> bool:
    return ts.commitment() == committed_hex.lower()


# ------------------------------------------------------------------ statistics and verification
def binom_sf(k: int, n: int, p: float) -> float:
    """P[Bin(n, p) >= k], exact."""
    if k <= 0:
        return 1.0
    return float(sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def threshold(n: int, num_classes: int, fpr: float = DEFAULT_FPR) -> int:
    """Smallest match count k with P[Bin(n, 1/K) >= k] <= fpr."""
    for k in range(n + 1):
        if binom_sf(k, n, 1 / num_classes) <= fpr:
            return k
    return n + 1


@dataclass(frozen=True)
class Result:
    matches: int
    n: int
    accuracy: float
    p_value: float            # P[Bin(n, 1/K) >= matches]: chance a model that never saw the set does this well
    threshold: int
    accepted: bool

    def to_dict(self) -> dict:
        return {"matches": self.matches, "n": self.n, "accuracy": self.accuracy, "p_value": self.p_value,
                "threshold": self.threshold, "accepted": self.accepted}


def score(predicted_labels, ts: TriggerSet, k: int | None = None, fpr: float = DEFAULT_FPR) -> Result:
    pred = np.asarray(predicted_labels).reshape(-1)
    if pred.shape[0] != ts.n:
        raise ValueError("one prediction per trigger image is needed")
    m = int(np.count_nonzero(pred.astype(np.int64) == ts.labels.astype(np.int64)))
    k = threshold(ts.n, ts.num_classes, fpr) if k is None else int(k)
    return Result(matches=m, n=ts.n, accuracy=m / ts.n, p_value=binom_sf(m, ts.n, 1 / ts.num_classes),
                  threshold=k, accepted=m >= k)


def verify(predict, ts: TriggerSet, mean, std, k: int | None = None, fpr: float = DEFAULT_FPR) -> Result:
    """Black-box verification: ``predict(float32 array (n, C, H, W)) -> labels`` is the suspect's API."""
    return score(predict(ts.normalized(mean, std)), ts, k, fpr)


# ------------------------------------------------------------------ PyTorch helpers (optional dependency)
def torch_predictor(model, device=None, batch_size: int = 500):
    """Wrap a torch module as ``predict(np.ndarray) -> np.ndarray of labels`` (eval mode, no grad)."""
    import torch

    def predict(x: np.ndarray) -> np.ndarray:
        model.eval()
        dev = device or next(model.parameters()).device
        out = []
        with torch.no_grad():
            for i in range(0, x.shape[0], batch_size):
                out.append(model(torch.from_numpy(x[i:i + batch_size]).to(dev)).argmax(1).cpu())
        return torch.cat(out).numpy()
    return predict


def sampler(ts: TriggerSet, mean, std, per_batch: int, device=None):
    """``extra(generator) -> (x, y)`` for ``sigil.attacks.fit``: ``per_batch`` triggers drawn uniformly
    (with the training loop's seeded generator) and appended to every training batch."""
    import torch

    x = torch.from_numpy(ts.normalized(mean, std))
    y = torch.from_numpy(ts.labels.astype(np.int64))
    if device is not None:
        x, y = x.to(device), y.to(device)

    def extra(g):
        idx = torch.randint(0, ts.n, (per_batch,), generator=g).to(x.device)
        return x[idx], y[idx]
    return extra
