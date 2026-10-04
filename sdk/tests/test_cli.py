"""CLI owner/registry/verifier flows that need no ML framework (SDK-03) and encrypted secrets (CR-04)."""
import json

import pytest

from sigil import secretbox
from sigil.cli import main
from sigil.records import verify_receipt, verify_registration


def test_secretbox_roundtrip_and_wrong_passphrase(tmp_path):
    p = secretbox.save(tmp_path / "s.json", {"seed": "123"}, "a long passphrase", "seed")
    text = p.read_text()
    assert "123" not in text.replace('"schema"', "")
    assert secretbox.load(p, "a long passphrase", "seed") == {"seed": "123"}
    with pytest.raises(ValueError):
        secretbox.load(p, "wrong passphrase!", "seed")
    with pytest.raises(ValueError):
        secretbox.load(p, "a long passphrase", "other-kind")


def test_owner_registry_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIGIL_PASSPHRASE", "owner passphrase")
    monkeypatch.setenv("SIGIL_REGISTRY_PASSPHRASE", "registry passphrase")
    monkeypatch.chdir(tmp_path)
    run = lambda *a: (main(["--json", *a]), json.loads(capsys.readouterr().out))[1]   # noqa: E731
    k = run("keygen", "--out", "secrets/owner.key")
    r = run("registry-keygen", "--out", "secrets/registry.key")
    s = run("seed", "--owner", "secrets/owner.key", "--out", "secrets/seed.json", "--bits", "64")
    box = json.loads((tmp_path / "secrets/seed.json").read_text())
    assert s["config"]["max_err"] == 8
    assert set(box) == {"schema", "kind", "kdf", "salt", "nonce", "ciphertext"}   # nothing in the clear
    (tmp_path / "model.pt").write_bytes(b"pretend model bytes")
    reg = run("register", "model.pt", "--registry-key", "secrets/registry.key")
    rec = json.loads((tmp_path / "registration.json").read_text())
    rcp = json.loads((tmp_path / "registration.receipt.json").read_text())
    assert verify_registration(rec) == [] and rec["commitment"] == s["commitment"] == reg["commitment"]
    assert rec["owner_public_key"] == k["public_key"]
    assert verify_receipt(rcp, rec, {r["registry_public_key"]}) == []
    c = run("claim", "registration.json", "--suspect", "model.pt", "--out", "claim.json")
    claim = json.loads((tmp_path / c["claim"]).read_text())
    assert claim["registration_sha256"] == rcp["registration_sha256"]
