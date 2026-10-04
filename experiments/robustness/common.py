"""Shared helpers for the M5 robustness experiments (ROB-01..ROB-08, WM-06, WM-07, WM-09).

Results are schema-versioned JSON/CSV under experiments/robustness/results/ (committed); checkpoints go to
experiments/ckpt/robustness/ and datasets to experiments/data/ (both gitignored).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CKPT = ROOT / "experiments" / "ckpt" / "robustness"
DATA = ROOT / "experiments" / "data"
RESULT_SCHEMA = "sigil.robustness.results/v1"

sys.path.insert(0, str(ROOT / "demo"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except AttributeError:
        pass

from sigil import protocol as P  # noqa: E402
from sigil.identity import KeyPair  # noqa: E402


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def git_commit() -> dict:
    def run(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


def env_info(dev: torch.device) -> dict:
    return {
        "git": git_commit(), "torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
        "device": str(dev), "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
        "cudnn_deterministic": torch.backends.cudnn.deterministic, "platform": platform.platform(),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg["_path"] = str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")
    cfg["_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return cfg


# ------------------------------------------------------------------ identities and seeds (labelled, reproducible)
def seed_int(label: str) -> int:
    """A 248-bit protocol seed derived from a public label. EXPERIMENT ONLY: real seeds come from new_seed()."""
    return int.from_bytes(hashlib.sha256(label.encode()).digest(), "big") >> 8


def keypair(label: str) -> KeyPair:
    """A deterministic Ed25519 key pair for experiments (never use a labelled key for a real model)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return KeyPair(Ed25519PrivateKey.from_private_bytes(hashlib.sha256(label.encode()).digest()))


class Owner:
    """Everything one party needs for protocol v2 under one config."""

    def __init__(self, label: str, cfg: P.Config):
        self.label, self.cfg = label, cfg
        self.keys = keypair(f"{label}/ed25519")
        self.pkh = P.pk_hash(self.keys.public_bytes)
        self.seed = seed_int(f"{label}/seed")
        self.X = P.key_matrix(self.seed, self.pkh, cfg).astype(np.float32)
        self.b = P.signature_bits(self.seed, self.pkh, cfg)

    def detect(self, w: np.ndarray) -> P.Detection:
        return P.detect(self.seed, self.pkh, self.cfg, w)


# ------------------------------------------------------------------ statistics
def stats(vals) -> dict:
    a = np.asarray([v for v in vals if v is not None], dtype=float)
    if a.size == 0:
        return {"mean": None, "std": None, "n": 0}
    return {"mean": float(a.mean()), "std": float(a.std(ddof=1)) if a.size > 1 else 0.0, "n": int(a.size),
            "min": float(a.min()), "max": float(a.max())}


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided (1 - alpha) binomial interval; the upper end is the 95% upper bound used for FPR."""
    from scipy.stats import beta
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


def binom_cdf(k: int, n: int, p: float = 0.5) -> float:
    return float(sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1)))


# ------------------------------------------------------------------ files
def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=_jsonable), encoding="utf-8")
    tmp.replace(path)


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cached(path: Path, factory, build, dev):
    """Load ``factory()``'s weights from ``path`` (weights_only) if present, else ``build()`` and save."""
    m = factory().to(dev)
    if path.exists():
        m.load_state_dict(torch.load(path, map_location=dev, weights_only=True))
        m.eval()
        return m, False
    m = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    torch.save(m.state_dict(), tmp)
    tmp.replace(path)
    return m, True


class GpuClock:
    """Wall-clock seconds spent in GPU work (training, attacks, evaluation), accumulated per script."""

    def __init__(self):
        self.seconds = 0.0
        self._t = None

    def __enter__(self):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        self._t = time.time()
        return self

    def __exit__(self, *exc):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        self.seconds += time.time() - self._t


def retry_oom(fn, *args, batch_key="batch_size", **kw):
    """Call fn; on CUDA OOM halve kw[batch_key] (if given) and retry (another job shares the GPU)."""
    while True:
        try:
            return fn(*args, **kw)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if batch_key not in kw or kw[batch_key] <= 16:
                raise
            kw[batch_key] //= 2
            log(f"CUDA OOM: retrying with {batch_key}={kw[batch_key]}")
