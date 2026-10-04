"""Identities, registrations, registry receipts, disputes and claims (CR-01, CR-02, CR-03)."""
import copy

import pytest

from sigil import protocol as P
from sigil.identity import KeyPair, verify_signature
from sigil.records import (canonical_json, earliest, make_claim, make_receipt, make_registration,
                           registration_hash, verify_receipt, verify_registration)

CFG = P.Config()


def test_key_roundtrip_and_wrong_passphrase(tmp_path):
    k = KeyPair.generate()
    path = k.save(tmp_path / "owner.key", "correct horse")
    assert b"ENCRYPTED" in path.read_bytes()
    assert KeyPair.load(path, "correct horse").public_bytes == k.public_bytes
    with pytest.raises(ValueError):
        KeyPair.load(path, "wrong passphrase")
    with pytest.raises(ValueError):
        k.save(tmp_path / "x.key", "short")
    assert verify_signature(k.public_bytes, k.sign(b"m"), b"m")
    assert not verify_signature(k.public_bytes, k.sign(b"m"), b"n")


def test_canonical_json_rejects_floats():
    assert canonical_json({"b": 1, "a": "x"}) == b'{"a":"x","b":1}'
    with pytest.raises(TypeError):
        canonical_json({"a": 0.5})


def test_registration_valid_and_tamper_evident():
    owner = KeyPair.generate()
    rec = make_registration(owner, P.new_seed(), CFG, "ab" * 32)
    assert verify_registration(rec) == []
    assert "seed" not in str(rec).lower()
    for field, value in [("model_sha256", "cd" * 32), ("commitment", "1"), ("created_at", "2020-01-01T00:00:00Z")]:
        bad = copy.deepcopy(rec)
        bad[field] = value
        assert "owner signature is invalid" in verify_registration(bad)
    bad = copy.deepcopy(rec)
    bad["config"]["max_err"] = 20
    assert verify_registration(bad)


def test_receipts_and_dispute_rule():
    registry, other_registry = KeyPair.generate(), KeyPair.generate()
    owner, thief = KeyPair.generate(), KeyPair.generate()
    r_owner = make_registration(owner, P.new_seed(), CFG, "ab" * 32, created_at="2026-10-01T10:00:00Z")
    r_thief = make_registration(thief, P.new_seed(), CFG, "ab" * 32, created_at="2026-10-03T10:00:00Z")
    rc_owner = make_receipt(registry, r_owner, registered_at="2026-10-01T10:00:05Z")
    rc_thief = make_receipt(registry, r_thief, registered_at="2026-10-03T10:00:05Z")
    trusted = {registry.public_hex}
    assert verify_receipt(rc_owner, r_owner, trusted) == []
    assert verify_receipt(rc_owner, r_thief, trusted)                       # wrong registration
    assert verify_receipt(make_receipt(other_registry, r_owner), r_owner, trusted)   # untrusted registry
    forged = dict(rc_thief, registered_at="2026-09-01T00:00:00Z")           # back-dating breaks the signature
    assert "registry signature is invalid" in verify_receipt(forged, r_thief, trusted)
    assert earliest([(r_thief, rc_thief), (r_owner, rc_owner)])[0] is r_owner


def test_claim_has_fresh_nonce():
    rec = make_registration(KeyPair.generate(), P.new_seed(), CFG, "ab" * 32)
    c1, c2 = make_claim(rec, "ef" * 32), make_claim(rec, "ef" * 32)
    assert c1["nonce"] != c2["nonce"] and c1["registration_sha256"] == registration_hash(rec)


def test_timestamps_are_millisecond_precise_and_compared_as_times():
    from sigil.records import parse_time, utc_now
    t = utc_now()
    assert t.endswith("Z") and "." in t
    assert parse_time("2026-10-05T03:05:18Z") < parse_time("2026-10-05T03:05:18.123Z")
    assert parse_time("2026-10-05T03:05:18.999Z") < parse_time("2026-10-05T03:05:19Z")
