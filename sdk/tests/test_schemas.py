"""SDK-05: every file format has a JSON Schema, and real files match it."""
import copy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from sigil import protocol as P  # noqa: E402
from sigil import schemas  # noqa: E402
from sigil.identity import KeyPair  # noqa: E402
from sigil.records import make_claim, make_receipt, make_registration  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAVED = {"registration": "demo/ckpt/v2/registration.json", "receipt": "demo/ckpt/v2/receipt.json",
         "claim": "demo/results/protocol_v2/claim.json", "proof": "demo/results/protocol_v2/proof.json",
         "public": "demo/results/protocol_v2/public.json"}


def _invalid(name, obj) -> bool:
    return not schemas.validator(name).is_valid(obj)


@pytest.mark.parametrize("name", schemas.NAMES)
def test_every_schema_is_valid_draft_2020_12(name):
    s = schemas.load(name)
    jsonschema.Draft202012Validator.check_schema(s)
    assert s["$id"] == f"urn:sigil:schema:{name}:v2"


@pytest.mark.parametrize("name,path", SAVED.items())
def test_saved_demo_files_match(name, path):
    schemas.validate(name, json.loads((ROOT / path).read_text(encoding="utf-8")))


def test_fresh_records_match_and_broken_ones_do_not():
    owner, registry = KeyPair.generate(), KeyPair.generate()
    rec = make_registration(owner, P.new_seed(), P.Config(T=256, max_err=32), "ab" * 32)
    rcp, claim = make_receipt(registry, rec), make_claim(rec, "cd" * 32)
    for name, obj in (("registration", rec), ("receipt", rcp), ("claim", claim)):
        schemas.validate(name, obj)
    for broken in ({**rec, "extra": "x"}, {k: v for k, v in rec.items() if k != "owner_signature"},
                   {**rec, "commitment": 5}, {**rec, "model_sha256": "AB" * 32}, {**rec, "created_at": "yesterday"}):
        assert _invalid("registration", broken)
    cfg = copy.deepcopy(rec)
    cfg["config"]["norm"] = "l2"
    assert _invalid("registration", cfg)
    assert _invalid("claim", {**claim, "nonce": "-1"})


def test_proof_and_public_shapes():
    proof = json.loads((ROOT / SAVED["proof"]).read_text())
    public = json.loads((ROOT / SAVED["public"]).read_text())
    assert _invalid("proof", {**proof, "protocol": "plonk"})
    assert _invalid("proof", {**proof, "pi_b": proof["pi_b"][:2]})
    assert _invalid("public", public[:4]) and _invalid("public", [*public, "1"])
    assert _invalid("public", [*public[:4], 7])


def test_bundle_manifest():
    good = {"schema": "sigil.bundle/v2", "circuit": "ownership_T64_M288_E8_W24", "vkey_sha256": "0f" * 32,
            "files": ["proof.json", "public.json", "claim.json"], "created_at": "2026-10-28T10:00:00.000Z"}
    schemas.validate("bundle", good)
    assert _invalid("bundle", {**good, "circuit": "../evil"})
    assert _invalid("bundle", {**good, "files": ["proof.json", "proof.json", "claim.json"]})


def test_unknown_schema_name():
    with pytest.raises(ValueError):
        schemas.load("seed")
