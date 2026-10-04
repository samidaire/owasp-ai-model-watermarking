"""The registry's Ed25519 key (CR-03): it timestamps registrations (sigil.records.make_receipt) and signs
certificates, audit exports and compliance reports.

The key is a sigil.identity.KeyPair, stored as passphrase-encrypted PKCS#8 (identity.KeyPair.save) at
SIGIL_REGISTRY_KEY (default backend/var/registry.key) and created on first run. The passphrase comes from
SIGIL_REGISTRY_PASSPHRASE. If that is unset (development), a random passphrase is generated once and kept
next to the key in backend/var/registry.passphrase (owner-only permissions) with a warning in the log; set the
variable for any real deployment. Neither file is ever served or committed (backend/var is gitignored).
"""
from __future__ import annotations

import base64
import copy
import os
import secrets
from datetime import datetime, timezone

from sigil.identity import KeyPair, verify_signature
from sigil.records import canonical_json

from .logs import log

SIGNED_SCHEMA_KEY = "registry_signature"


def _passphrase(settings) -> str:
    if settings.registry_passphrase is not None:
        return settings.registry_passphrase.get_secret_value()
    pfile = settings.registry_key.with_name(settings.registry_key.name.replace(".key", "") + ".passphrase")
    if not pfile.exists():
        pfile.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(pfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(32))
    log.warning("SIGIL_REGISTRY_PASSPHRASE is not set: using the development passphrase file in the var folder")
    return pfile.read_text(encoding="utf-8").strip()


class Registry:
    def __init__(self, keypair: KeyPair, extra_trusted: set[str] | None = None):
        self.key = keypair
        self.public_key = keypair.public_hex
        self.trusted = {self.public_key, *(extra_trusted or set())}

    @classmethod
    def load_or_create(cls, settings) -> "Registry":
        path = settings.registry_key
        passphrase = _passphrase(settings)
        if path.exists():
            kp = KeyPair.load(path, passphrase)
        else:
            kp = KeyPair.generate()
            kp.save(path, passphrase)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            log.info("created a new registry key", extra={"event": "registry.key_created"})
        return cls(kp, settings.extra_registry_keys)

    # ------------------------------------------------------------------ signed documents
    def sign_document(self, doc: dict) -> dict:
        """Return a copy of `doc` with registry_public_key and registry_signature (Ed25519 over canonical JSON,
        sigil.records.canonical_json: no floats)."""
        out = copy.deepcopy(doc)
        out.pop(SIGNED_SCHEMA_KEY, None)
        out["registry_public_key"] = self.public_key
        out["signed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out[SIGNED_SCHEMA_KEY] = base64.b64encode(self.key.sign(canonical_json(out))).decode("ascii")
        return out


def verify_document(doc: dict, trusted_keys: set[str]) -> list[str]:
    """Problems with a registry-signed document (empty list = valid)."""
    problems = []
    try:
        pk = doc["registry_public_key"]
        if pk not in trusted_keys:
            problems.append("not signed by a trusted registry")
        body = {k: v for k, v in doc.items() if k != SIGNED_SCHEMA_KEY}
        sig = base64.b64decode(doc[SIGNED_SCHEMA_KEY].encode("ascii"), validate=True)
        if not verify_signature(bytes.fromhex(pk), sig, canonical_json(body)):
            problems.append("registry signature is invalid")
    except (KeyError, ValueError, TypeError) as e:
        problems.append(f"malformed signed document: {e}")
    return problems


def no_floats(obj):
    """Signed documents are canonical JSON without floats: floats become their shortest repr strings."""
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, dict):
        return {str(k): no_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [no_floats(v) for v in obj]
    return obj
