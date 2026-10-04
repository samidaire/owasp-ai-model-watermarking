"""Powers of Tau files for Groth16 (ZK-04): download once, verify, cache for offline use.

Source: the Privacy & Scaling Explorations "Perpetual Powers of Tau" ceremony (80 contributions,
pot28_0080), prepared for SnarkJS and linked from the official README at
https://github.com/privacy-scaling-explorations/perpetualpowersoftau . (The Hermez/Polygon mirrors
listed in the SnarkJS README answer HTTP 403 as of October 2026.)

PSE publishes no checksums for the prepared files, so trust is established in two steps:
  1. the first download is verified with `snarkjs powersoftau verify`, which checks every contribution
     in the transcript and the consistency of all points;
  2. its BLAKE2b-512 is then pinned in PINNED below, and every later download must match it.
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

URL = "https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_{k:02d}.ptau"
FILENAME = "ppot_0080_{k:02d}.ptau"
SUPPORTED = range(8, 25)
# BLAKE2b-512 of files that passed `snarkjs powersoftau verify` (step 2 above).
PINNED: dict[int, str] = {}


def cache_dir() -> Path:
    """Where ptau files live: $SIGIL_PTAU_DIR, else ~/.cache/sigil/ptau (outside git, survives clones)."""
    d = Path(os.environ.get("SIGIL_PTAU_DIR") or Path.home() / ".cache" / "sigil" / "ptau")
    d.mkdir(parents=True, exist_ok=True)
    return d


def blake2b_file(path: Path) -> str:
    h = hashlib.blake2b(digest_size=64)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def power_for(n_constraints: int, n_public: int = 0) -> int:
    """Smallest k with 2**k >= constraints + public inputs + 1."""
    k = max(SUPPORTED.start, (n_constraints + n_public + 1 - 1).bit_length())
    if k not in SUPPORTED:
        raise ValueError(f"{n_constraints} constraints need a ptau beyond 2^{SUPPORTED.stop - 1}")
    return k


def get_ptau(k: int, download: bool = True) -> Path:
    """Path to a verified ppot_0080_k.ptau, downloading it if allowed and missing."""
    if k not in SUPPORTED:
        raise ValueError(f"unsupported ptau power {k}")
    path = cache_dir() / FILENAME.format(k=k)
    if not path.exists():
        if not download:
            raise FileNotFoundError(f"{path} missing; fetch it while online (sigil.zk.ptau.get_ptau({k}))")
        tmp = path.with_suffix(".part")
        print(f"downloading {URL.format(k=k)} -> {path}")
        urllib.request.urlretrieve(URL.format(k=k), tmp)
        os.replace(tmp, path)
    if k in PINNED:
        if blake2b_file(path) != PINNED[k]:
            bad = path.with_suffix(".bad")
            path.replace(bad)
            raise ValueError(f"{path.name}: BLAKE2b mismatch with the pinned value (moved to {bad.name})")
    else:
        marker = path.with_suffix(".verified")
        if not marker.exists() or marker.read_text().strip() != blake2b_file(path):
            raise ValueError(f"{path.name} has no pinned hash and has not been verified: run "
                             f"`snarkjs powersoftau verify {path}`, then write its BLAKE2b to {marker.name}")
    return path
