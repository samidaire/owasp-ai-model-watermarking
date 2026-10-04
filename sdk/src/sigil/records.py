"""Signed registrations, registry timestamps and ownership claims (CR-02, CR-03; docs/protocol.md §5).

Records are canonical JSON: keys sorted, no insignificant whitespace, UTF-8, integers and strings only
(no floats), which coincides with RFC 8785 (JCS) for these schemas. Field elements are decimal strings.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone

from .field import P
from .identity import KeyPair, verify_signature
from .protocol import Config, commitment, config_hash, pk_hash

REG_SCHEMA = "sigil.registration/v2"
RECEIPT_SCHEMA = "sigil.receipt/v2"
CLAIM_SCHEMA = "sigil.claim/v2"


def _check_values(obj):
    if isinstance(obj, float):
        raise TypeError("records may not contain floats (canonical JSON); use integers or strings")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise TypeError("record keys must be strings")
            _check_values(v)
    elif isinstance(obj, list):
        for v in obj:
            _check_values(v)


def canonical_json(obj) -> bytes:
    _check_values(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"), validate=True)


def _without(rec: dict, key: str) -> dict:
    return {k: v for k, v in rec.items() if k != key}


# ------------------------------------------------------------------ registration (owner-signed)
def make_registration(owner: KeyPair, seed: int, cfg: Config, model_sha256: str,
                      created_at: str | None = None) -> dict:
    """The public record an owner publishes at embedding time. Contains no secret."""
    pkh = pk_hash(owner.public_bytes)
    rec = {
        "schema": REG_SCHEMA,
        "owner_public_key": owner.public_hex,
        "pk_hash": str(pkh),
        "config": cfg.to_dict(),
        "config_hash": str(config_hash(cfg)),
        "commitment": str(commitment(seed, pkh, cfg)),
        "model_sha256": model_sha256,
        "created_at": created_at or utc_now(),
    }
    rec["owner_signature"] = _b64(owner.sign(canonical_json(rec)))
    return rec


def registration_hash(rec: dict) -> str:
    return sha256_hex(canonical_json(rec))


def verify_registration(rec: dict) -> list[str]:
    """Problems with a registration record (empty list = valid). Recomputes every derived field."""
    problems = []
    try:
        if rec.get("schema") != REG_SCHEMA:
            problems.append("unknown schema")
        pk = bytes.fromhex(rec["owner_public_key"])
        cfg = Config.from_dict(rec["config"])
        if rec["pk_hash"] != str(pk_hash(pk)):
            problems.append("pk_hash does not match the owner public key")
        if rec["config_hash"] != str(config_hash(cfg)):
            problems.append("config_hash does not match the config")
        if not 0 <= int(rec["commitment"]) < P:
            problems.append("commitment is not a field element")
        if not verify_signature(pk, _unb64(rec["owner_signature"]), canonical_json(_without(rec, "owner_signature"))):
            problems.append("owner signature is invalid")
    except (KeyError, ValueError, TypeError) as e:
        problems.append(f"malformed registration: {e}")
    return problems


# ------------------------------------------------------------------ registry receipt (timestamp)
def make_receipt(registry: KeyPair, rec: dict, registered_at: str | None = None) -> dict:
    """The registry's signed statement that it saw this exact registration at this time."""
    r = {"schema": RECEIPT_SCHEMA, "registration_sha256": registration_hash(rec),
         "registered_at": registered_at or utc_now(), "registry_public_key": registry.public_hex}
    r["registry_signature"] = _b64(registry.sign(canonical_json(r)))
    return r


def verify_receipt(receipt: dict, rec: dict, trusted_registry_keys: set[str]) -> list[str]:
    problems = []
    try:
        if receipt.get("schema") != RECEIPT_SCHEMA:
            problems.append("unknown receipt schema")
        if receipt["registry_public_key"] not in trusted_registry_keys:
            problems.append("receipt is not from a trusted registry")
        if receipt["registration_sha256"] != registration_hash(rec):
            problems.append("receipt is for a different registration")
        if not verify_signature(bytes.fromhex(receipt["registry_public_key"]), _unb64(receipt["registry_signature"]),
                                canonical_json(_without(receipt, "registry_signature"))):
            problems.append("registry signature is invalid")
    except (KeyError, ValueError, TypeError) as e:
        problems.append(f"malformed receipt: {e}")
    return problems


def earliest(candidates: list[tuple[dict, dict]]) -> tuple[dict, dict] | None:
    """Dispute rule: among (registration, receipt) pairs that are already verified, the earliest wins."""
    return min(candidates, key=lambda c: c[1]["registered_at"], default=None)


# ------------------------------------------------------------------ claim (verifier-issued)
def make_claim(rec: dict, suspect_model_sha256: str) -> dict:
    """A verifier opens a claim with a fresh nonce; the owner's proof must carry this nonce."""
    return {"schema": CLAIM_SCHEMA, "claim_id": str(uuid.uuid4()), "nonce": str(secrets.randbelow(P)),
            "registration_sha256": registration_hash(rec), "suspect_model_sha256": suspect_model_sha256,
            "opened_at": utc_now()}
