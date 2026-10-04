"""Owner and registry identities: Ed25519 key pairs (CR-01, ECC per the SOP's "RSA / ECC").

Private keys are stored as PKCS#8 PEM encrypted with the passphrase
(cryptography's BestAvailableEncryption), and are never written anywhere else.
"""
from __future__ import annotations

from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class KeyPair:
    """An Ed25519 key pair. Use for owners (signing registrations) and for the registry (timestamps)."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._sk = private_key

    @classmethod
    def generate(cls) -> "KeyPair":
        return cls(Ed25519PrivateKey.generate())

    @property
    def public_bytes(self) -> bytes:
        return self._sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @property
    def public_hex(self) -> str:
        return self.public_bytes.hex()

    def sign(self, data: bytes) -> bytes:
        return self._sk.sign(data)

    def save(self, path: str | Path, passphrase: str) -> Path:
        if len(passphrase) < 8:
            raise ValueError("use a passphrase of at least 8 characters")
        pem = self._sk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.BestAvailableEncryption(passphrase.encode("utf-8")))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(pem)
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, path: str | Path, passphrase: str) -> "KeyPair":
        try:
            sk = serialization.load_pem_private_key(Path(path).read_bytes(), passphrase.encode("utf-8"))
        except (ValueError, TypeError) as e:
            raise ValueError("could not decrypt the key: wrong passphrase or not a sigil key") from e
        if not isinstance(sk, Ed25519PrivateKey):
            raise ValueError("not an Ed25519 key")
        return cls(sk)


def verify_signature(public_key: bytes, signature: bytes, data: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
        return True
    except (InvalidSignature, ValueError):
        return False
