"""Encrypted-at-rest JSON for owner secrets such as the watermark seed (CR-04).

scrypt (n=2^15, r=8, p=1) derives a 256-bit key from the passphrase; AES-256-GCM encrypts the JSON.
The file says what it is but reveals nothing else.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

SCHEMA = "sigil.secret/v1"
_N, _R, _P = 2 ** 15, 8, 1


def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=_N, r=_R, p=_P).derive(passphrase.encode("utf-8"))


def save(path: str | Path, obj: dict, passphrase: str, kind: str) -> Path:
    if len(passphrase) < 8:
        raise ValueError("use a passphrase of at least 8 characters")
    salt, nonce = os.urandom(16), os.urandom(12)
    aad = f"{SCHEMA}:{kind}".encode()
    ct = AESGCM(_key(passphrase, salt)).encrypt(nonce, json.dumps(obj).encode("utf-8"), aad)
    box = {"schema": SCHEMA, "kind": kind, "kdf": {"name": "scrypt", "n": _N, "r": _R, "p": _P},
           "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
           "ciphertext": base64.b64encode(ct).decode()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(box, indent=2))
    tmp.replace(path)
    return path


def load(path: str | Path, passphrase: str, kind: str) -> dict:
    box = json.loads(Path(path).read_text())
    if box.get("schema") != SCHEMA or box.get("kind") != kind:
        raise ValueError(f"{path} is not a sigil {kind} secret")
    kdf = box["kdf"]
    if kdf != {"name": "scrypt", "n": _N, "r": _R, "p": _P}:
        raise ValueError("unsupported key derivation parameters")
    try:
        pt = AESGCM(_key(passphrase, base64.b64decode(box["salt"]))).decrypt(
            base64.b64decode(box["nonce"]), base64.b64decode(box["ciphertext"]), f"{SCHEMA}:{kind}".encode())
    except InvalidTag as e:
        raise ValueError("wrong passphrase or corrupted secret file") from e
    return json.loads(pt)
