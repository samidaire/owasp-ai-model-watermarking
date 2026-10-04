"""Protocol v2: committed-seed watermark keys bound to an owner key (docs/protocol.md).

Everything an ownership proof depends on is defined here once, in integer/field arithmetic, so the
Circom circuit (circuits/ownership.circom) can compute exactly the same values:

    pk_hash     = Poseidon(DOM_PK, pk[0:16], pk[16:32])                    Ed25519 public key
    config_hash = Poseidon(DOM_CFG, version, T, M, scale_bits, w_bits, max_err, layer, norm, prg_bits)
    C           = Poseidon(DOM_COMMIT, seed, pk_hash, config_hash)         the published commitment
    key bits    = low PRG_BITS bits of Poseidon(DOM_KEY, seed, pk_hash, k), k = 0, 1, ...
    X[i][j]     = 2 * keybit[i*M + j] - 1                                   in {-1, +1}, T x M
    signature   = low PRG_BITS bits of Poseidon(DOM_SIG, seed, pk_hash, k), first T bits
    w_q         = round(w * 2**scale_bits), |w_q| < 2**w_bits             w: Uchida vector of the layer
    bit_i       = 1 if sum_j X[i][j] * w_q[j] >= 0 else 0
    accept      = #{i : bit_i != signature_i} <= max_err
    w_hash      = Poseidon sponge over (w_q + 2**w_bits), 15 per call, then Poseidon(h, M)

Both the key and the signature depend on the seed AND the owner key, so a thief cannot search
owner identities against a fixed key (FIX-04), and the config is part of the commitment (FIX-05).
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict, dataclass

import numpy as np

from .field import P, to_field
from .poseidon import poseidon

PROTOCOL_VERSION = 2
DOM_KEY, DOM_SIG, DOM_COMMIT, DOM_W, DOM_PK, DOM_CFG = 1, 2, 3, 4, 5, 6
PRG_BITS = 200          # bits used per Poseidon output: the low 200 bits of a uniform field element
                        # are within 2**-53 of uniform (P > 2**253)
SEED_BITS = 248
W_CHUNK = 15            # values absorbed per sponge call (Poseidon with 16 inputs)
LAYOUTS = ("OIHW", "HWIO", "OI", "IO")   # torch conv, keras conv, torch linear, keras dense


def _tag(text: str) -> int:
    """A field element naming a string (first 31 bytes of SHA-256, so always < P)."""
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:31], "big")


@dataclass(frozen=True)
class Config:
    """Public watermark parameters. Fixed at embedding time and committed via config_hash."""
    T: int = 64                 # signature length in bits
    M: int = 288                # length of the Uchida vector (in_channels * kh * kw for conv)
    layer: str = "conv2"        # name of the watermarked layer
    scale_bits: int = 16        # fixed-point scale: w_q = round(w * 2**scale_bits)
    w_bits: int = 24            # range bound: |w_q| < 2**w_bits
    max_err: int = 8            # accept iff at most max_err of T bits disagree (theta = max_err / T)
    norm: str = "none"          # normalisation applied to w before quantising (v2: none)

    def __post_init__(self):
        if not (1 <= self.T <= 1024 and 1 <= self.M <= 1 << 16):
            raise ValueError("T must be 1..1024 and M 1..65536")
        if not 0 <= self.max_err < self.T:
            raise ValueError("max_err must be in [0, T)")
        if not 1 <= self.scale_bits < self.w_bits <= 64:
            raise ValueError("need 1 <= scale_bits < w_bits <= 64")
        if self.norm != "none":
            raise ValueError("protocol v2 defines norm='none' only")

    @property
    def theta(self) -> float:
        return self.max_err / self.T

    @property
    def sum_bits(self) -> int:
        """Bits needed for |sum_j X_ij w_q_j| < 2**sum_bits (used by the circuit's sign test)."""
        return self.w_bits + max(1, (self.M - 1).bit_length()) + 1

    def to_dict(self) -> dict:
        return {"protocol": PROTOCOL_VERSION, **asdict(self), "prg_bits": PRG_BITS}

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        if d.get("protocol", PROTOCOL_VERSION) != PROTOCOL_VERSION or d.get("prg_bits", PRG_BITS) != PRG_BITS:
            raise ValueError("config is not protocol v2")
        return cls(**{k: d[k] for k in ("T", "M", "layer", "scale_bits", "w_bits", "max_err", "norm")})


# ------------------------------------------------------------------ hashes and derivations
def config_hash(cfg: Config) -> int:
    return poseidon([DOM_CFG, PROTOCOL_VERSION, cfg.T, cfg.M, cfg.scale_bits, cfg.w_bits, cfg.max_err,
                     _tag(cfg.layer), _tag(cfg.norm), PRG_BITS])


def pk_hash(public_key: bytes) -> int:
    if len(public_key) != 32:
        raise ValueError("expected a 32-byte Ed25519 public key")
    return poseidon([DOM_PK, int.from_bytes(public_key[:16], "big"), int.from_bytes(public_key[16:], "big")])


def new_seed() -> int:
    """A fresh secret seed: 248 uniformly random bits (a canonical field element)."""
    return secrets.randbits(SEED_BITS)


def _check_seed(seed: int) -> int:
    seed = int(seed)
    if not 0 <= seed < 1 << SEED_BITS:
        raise ValueError(f"seed must be a {SEED_BITS}-bit integer")
    return seed


def commitment(seed: int, pkh: int, cfg: Config) -> int:
    return poseidon([DOM_COMMIT, _check_seed(seed), pkh, config_hash(cfg)])


def _stream_bits(domain: int, seed: int, pkh: int, n: int) -> np.ndarray:
    blocks = -(-n // PRG_BITS)
    out = np.empty(blocks * PRG_BITS, dtype=np.uint8)
    for k in range(blocks):
        r = poseidon([domain, _check_seed(seed), pkh, k])
        low = r & ((1 << PRG_BITS) - 1)
        # bit t of the block is (low >> t) & 1, matching Num2Bits output order in the circuit
        out[k * PRG_BITS:(k + 1) * PRG_BITS] = np.unpackbits(
            np.frombuffer(low.to_bytes(PRG_BITS // 8, "little"), dtype=np.uint8), bitorder="little")
    return out[:n]


def key_matrix(seed: int, pkh: int, cfg: Config) -> np.ndarray:
    """The secret projection X in {-1, +1}^(T x M), row-major from the key bit stream."""
    bits = _stream_bits(DOM_KEY, seed, pkh, cfg.T * cfg.M).reshape(cfg.T, cfg.M)
    return bits.astype(np.int8) * 2 - 1


def signature_bits(seed: int, pkh: int, cfg: Config) -> np.ndarray:
    return _stream_bits(DOM_SIG, seed, pkh, cfg.T)


# ------------------------------------------------------------------ the suspect model's vector
def uchida_vector(kernel, layout: str) -> np.ndarray:
    """Canonical Uchida vector of a layer's weights: mean over output units, ordered (in, kh, kw).

    Computed in float64 from the stored float32 weights so every framework gives identical values.
    layout: 'OIHW' (PyTorch Conv2d), 'HWIO' (Keras Conv2D), 'OI' (PyTorch Linear), 'IO' (Keras Dense).
    """
    k = np.asarray(kernel, dtype=np.float64)
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    if layout == "HWIO":
        k = np.transpose(k, (3, 2, 0, 1))      # -> OIHW
    elif layout == "IO":
        k = k.T                                # -> OI
    if (k.ndim, layout in ("OIHW", "HWIO")) not in ((4, True), (2, False)):
        raise ValueError(f"kernel shape {np.shape(kernel)} does not match layout {layout}")
    # Same memory layout for every framework, so the float64 reduction runs in the same order and the
    # vector is bit-identical whether the kernel arrived as OIHW, HWIO, OI or IO.
    k = np.ascontiguousarray(k)
    return (np.add.reduce(k, axis=0) / k.shape[0]).reshape(-1)


def quantize(w, cfg: Config) -> np.ndarray:
    w = np.asarray(w, dtype=np.float64).reshape(-1)
    if w.shape[0] != cfg.M:
        raise ValueError(f"expected a vector of length M={cfg.M}, got {w.shape[0]}")
    if not np.all(np.isfinite(w)):
        raise ValueError("weights contain NaN or inf")
    q = np.rint(w * float(1 << cfg.scale_bits)).astype(np.int64)
    if np.any(np.abs(q) >= 1 << cfg.w_bits):
        raise ValueError(f"|w * 2**{cfg.scale_bits}| exceeds 2**{cfg.w_bits}: choose a smaller scale")
    return q


def w_hash(w_q, cfg: Config) -> int:
    """Binds a proof to the suspect model: the verifier recomputes this from the model file."""
    w_q = np.asarray(w_q, dtype=np.int64).reshape(-1)
    if w_q.shape[0] != cfg.M:
        raise ValueError("w_q has the wrong length")
    offset = 1 << cfg.w_bits
    vals = [int(v) + offset for v in w_q]
    if any(not 0 <= v < 1 << (cfg.w_bits + 1) for v in vals):
        raise ValueError("w_q out of range")
    h = DOM_W
    for i in range(0, cfg.M, W_CHUNK):
        chunk = vals[i:i + W_CHUNK]
        h = poseidon([h, *chunk, *([0] * (W_CHUNK - len(chunk)))])
    return poseidon([h, cfg.M])


# ------------------------------------------------------------------ detection
def projections(X: np.ndarray, w_q: np.ndarray) -> np.ndarray:
    return np.asarray(X, dtype=np.int64) @ np.asarray(w_q, dtype=np.int64)


def extract_bits(X: np.ndarray, w_q: np.ndarray) -> np.ndarray:
    return (projections(X, w_q) >= 0).astype(np.uint8)


def errors(bits, sig) -> int:
    return int(np.count_nonzero(np.asarray(bits, dtype=np.uint8) != np.asarray(sig, dtype=np.uint8)))


@dataclass(frozen=True)
class Detection:
    errors: int
    ber: float
    max_err: int
    accepted: bool

    def to_dict(self) -> dict:
        return asdict(self)


def detect(seed: int, pkh: int, cfg: Config, w) -> Detection:
    """Owner-side detection on a float Uchida vector (or an already quantised int vector)."""
    w_q = np.asarray(w) if np.asarray(w).dtype.kind == "i" else quantize(w, cfg)
    e = errors(extract_bits(key_matrix(seed, pkh, cfg), w_q), signature_bits(seed, pkh, cfg))
    return Detection(errors=e, ber=e / cfg.T, max_err=cfg.max_err, accepted=e <= cfg.max_err)


# ------------------------------------------------------------------ circuit input
def circuit_input(seed: int, w_q, pkh: int, cfg: Config, nonce: int) -> dict:
    """Witness input JSON for circuits/ownership.circom (all values as decimal strings)."""
    w_q = np.asarray(w_q, dtype=np.int64).reshape(-1)
    if not 0 <= int(nonce) < P:
        raise ValueError("nonce must be a field element")
    return {
        "seed": str(_check_seed(seed)),
        "w": [str(to_field(int(v))) for v in w_q],
        "scale_bits": str(cfg.scale_bits),
        "layer_tag": str(_tag(cfg.layer)),
        "norm_tag": str(_tag(cfg.norm)),
        "pk_hash": str(pkh),
        "config_hash": str(config_hash(cfg)),
        "commitment": str(commitment(seed, pkh, cfg)),
        "w_hash": str(w_hash(w_q, cfg)),
        "nonce": str(int(nonce)),
    }


PUBLIC_SIGNALS = ("pk_hash", "config_hash", "commitment", "w_hash", "nonce")
