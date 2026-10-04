"""Interim FIX-03: no artefact under demo/results/ may contain the owner's key X or signature s.

The DEMO seed is read from demo/ckpt/owner_secret.json, and X and s are re-derived exactly as
demo/wm_core.py does (derive_key, derive_signature), reimplemented here with numpy so no torch is
needed. Every file is scanned for the encodings a leak would actually take:
  signature: the 8 packed bytes, its hex, the 64-character bit string, s = +-1 as float32 (how the
             exported circuit model stored it), and 64-element JSON lists of the bits or of s;
  key:       the first 8 float32 values of every row of X and of X transposed (constant folding
             stored X.T in extract.onnx).
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "demo" / "results"
SECRET = REPO / "demo" / "ckpt" / "owner_secret.json"
T_BITS, M_DIM = 64, 288

# These results show the signature BY DESIGN in this demo (Panels A, C and D display it). Under
# API-03 (REQUIREMENTS.md) they become owner-only views. Key bytes are forbidden in them too.
SIGNATURE_ALLOWED = {"train.json", "forgery.json", "committed_seed.json"}
# Public, possibly huge, and never derived from the key: the KZG SRS and (if KEEP_PK=1) the proving key.
NOT_SCANNED_SUFFIXES = (".srs",)
NOT_SCANNED_NAMES = {"pk.key"}


def derive(seed: bytes, owner_id: str):
    """Same hashing as wm_core.derive_signature / derive_key."""
    h = hashlib.sha256(b"sig|" + seed + b"|" + owner_id.encode()).digest()
    bits = np.unpackbits(np.frombuffer(h, dtype=np.uint8))[:T_BITS]
    hk = hashlib.sha256(b"key|" + seed).digest()
    X = np.random.Generator(np.random.PCG64(int.from_bytes(hk, "big"))).standard_normal((T_BITS, M_DIM), dtype=np.float32)
    return bits, X


@pytest.fixture(scope="module")
def secret():
    s = json.loads(SECRET.read_text(encoding="utf-8"))
    bits, X = derive(bytes.fromhex(s["seed_hex"]), s["owner_id"])
    return bits, X


def patterns(bits, X):
    packed = np.packbits(bits).tobytes()
    s = bits.astype(np.float32) * 2 - 1
    sig = {"packed signature bytes": [packed],
           "signature hex": [packed.hex().encode(), packed.hex().upper().encode()],
           "signature bit string": ["".join(map(str, bits)).encode()],
           "signature as float32 +-1": [s.astype("<f4").tobytes()]}
    key = {"key X rows (float32)": [r.astype("<f4").tobytes()[:32] for r in X],
           "key X^T rows (float32)": [r.astype("<f4").tobytes()[:32] for r in np.ascontiguousarray(X.T)]}
    return sig, key


def json_lists(obj):
    if isinstance(obj, list):
        yield obj
        for v in obj:
            yield from json_lists(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from json_lists(v)


def findings(path: Path, data: bytes, bits, X, check_signature=True):
    sig, key = patterns(bits, X)
    groups = {**key, **(sig if check_signature else {})}
    found = [label for label, pats in groups.items() if any(p in data for p in pats)]
    if check_signature and path.suffix == ".json":
        try:
            doc = json.loads(data)
        except ValueError:
            doc = None
        s = [int(b) * 2 - 1 for b in bits]
        for lst in json_lists(doc):
            if len(lst) == T_BITS and (lst == [int(b) for b in bits] or lst == s):
                found.append("signature as a JSON list")
                break
    return found


def result_files():
    for p in sorted(RESULTS.rglob("*")):
        if p.is_file() and p.suffix not in NOT_SCANNED_SUFFIXES and p.name not in NOT_SCANNED_NAMES:
            yield p


def test_no_onnx_file_under_results():
    onnx = [p.relative_to(REPO).as_posix() for p in RESULTS.rglob("*.onnx*")]
    assert onnx == [], f"exported circuit models embed the key and signature: {onnx}"


def test_derivation_matches_the_saved_runs(secret):
    """Guards the scanner itself: the re-derived X and s are the ones the demo really used
    (checked against results made with the current owner key; stale results are skipped)."""
    bits, X = secret
    current = json.loads((RESULTS / "public_commitment.json").read_text(encoding="utf-8"))["commitment_sha256"]
    train = json.loads((RESULTS / "train.json").read_text(encoding="utf-8"))
    summary = json.loads((RESULTS / "ezkl_private_owner" / "summary.json").read_text())
    checked = 0
    if train.get("commitment") == current:
        assert train["signature_bits"] == bits.tolist()
        checked += 1
    if summary.get("commitment") == current:
        w = np.array(json.loads((RESULTS / "ezkl_private_owner" / "input.json").read_text())["input_data"][0], np.float32)
        margins = (X @ w) * (bits.astype(np.float32) * 2 - 1)
        assert float(margins.min()) == pytest.approx(summary["min_margin"], rel=1e-4)
        checked += 1
    if not checked:
        pytest.skip("saved results are stale (made with an older owner key)")


def test_scanner_detects_an_embedded_key_and_signature(secret, tmp_path):
    bits, X = secret
    leak = b"onnx header" + np.ascontiguousarray(X.T).astype("<f4").tobytes() + (bits * 2.0 - 1).astype("<f4").tobytes()
    assert set(findings(tmp_path / "extract.onnx", leak, bits, X)) == {
        "key X^T rows (float32)", "signature as float32 +-1"}
    as_json = json.dumps({"deep": {"bits": bits.tolist()}}).encode()
    assert findings(tmp_path / "x.json", as_json, bits, X) == ["signature as a JSON list"]
    assert findings(tmp_path / "x.json", as_json, bits, X, check_signature=False) == []


def test_no_result_file_contains_the_key_or_signature(secret):
    bits, X = secret
    leaks = {}
    for p in result_files():
        allowed = p.relative_to(RESULTS).as_posix() in SIGNATURE_ALLOWED
        found = findings(p, p.read_bytes(), bits, X, check_signature=not allowed)
        if found:
            leaks[p.relative_to(REPO).as_posix()] = found
    assert leaks == {}, f"secret material under demo/results/: {leaks}"
