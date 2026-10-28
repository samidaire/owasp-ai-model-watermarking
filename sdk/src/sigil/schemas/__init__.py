"""JSON Schemas (draft 2020-12) of sigil's file formats (SDK-05).

    from sigil import schemas
    schemas.validate("registration", json.loads(Path("registration.json").read_text()))   # raises if invalid

| Name | File | Written by |
|---|---|---|
| registration | registration.json | `sigil register` (owner-signed public record) |
| receipt | registration.receipt.json | `sigil register --registry-key`, `sigil receipt` |
| claim | claim.json | `sigil claim` (verifier, fresh nonce) |
| proof | bundle/proof.json | `sigil prove` (SnarkJS Groth16) |
| public | bundle/public.json | `sigil prove` (the five public signals) |
| bundle | bundle/bundle.json | `sigil prove` (circuit and verification-key hash) |

The schemas check structure only; signatures, hashes and the proof itself are checked by sigil.records and
sigil.verify. Loading a schema needs nothing extra; validate() needs the `jsonschema` package (the [dev] extra).
"""
from __future__ import annotations

import json
from importlib import resources

NAMES = ("registration", "receipt", "claim", "proof", "public", "bundle")


def load(name: str) -> dict:
    """The schema as a dict."""
    if name not in NAMES:
        raise ValueError(f"unknown schema {name!r}; expected one of {NAMES}")
    return json.loads(resources.files(__package__).joinpath(f"{name}.schema.json").read_text(encoding="utf-8"))


def validator(name: str):
    """A jsonschema Draft 2020-12 validator for `name`, resolving references between the sigil schemas."""
    import jsonschema
    from referencing import Registry, Resource

    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in map(load, NAMES))
    return jsonschema.Draft202012Validator(load(name), registry=registry)


def validate(name: str, obj) -> None:
    """Raise jsonschema.ValidationError if `obj` doesn't match the schema `name`."""
    validator(name).validate(obj)
