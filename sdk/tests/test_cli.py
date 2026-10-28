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


@pytest.mark.ml
@pytest.mark.zk
def test_cli_prove_and_verify_demo_f(tmp_path, monkeypatch, capsys):
    """Owner proves and verifier verifies through the CLI, with demo F's public demo identities and model."""
    from pathlib import Path
    from sigil.zk import circom as Z
    from sigil import protocol as P
    root = Path(__file__).resolve().parents[2]
    v2 = root / "demo" / "ckpt" / "v2"
    if not (Z.artifacts(P.Config()).zkey.exists() and (v2 / "watermarked_v2.pt").exists()):
        pytest.skip("needs the T=64 setup and demo F's saved model")
    monkeypatch.setenv("SIGIL_PASSPHRASE", "sigil-demo-only-passphrase")
    monkeypatch.setenv("SIGIL_REGISTRY_PASSPHRASE", "sigil-demo-only-passphrase")
    monkeypatch.chdir(tmp_path)
    model, clean = str(v2 / "watermarked_v2.pt"), str(root / "demo" / "ckpt" / "clean.pt")
    common = ["--owner", str(v2 / "owner.key"), "--seed", str(v2 / "seed.json")]
    assert main(["--json", "detect", model, *common]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is True
    assert main(["--json", "register", model, *common, "--registry-key", str(v2 / "registry.key")]) == 0
    capsys.readouterr()
    reg = json.loads((tmp_path / "registration.json").read_text())
    rcp = json.loads((tmp_path / "registration.receipt.json").read_text())
    assert main(["--json", "claim", "registration.json", "--suspect", model]) == 0
    capsys.readouterr()
    assert main(["--json", "prove", model, "--claim", "claim.json", *common, "--out", "bundle"]) == 0
    capsys.readouterr()
    trusted = ["--trusted-registry", rcp["registry_public_key"]]
    args = ["bundle", "--registration", "registration.json", "--receipt", "registration.receipt.json", *trusted]
    import time
    assert main(["--json", "verify", *args, "--suspect", model]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is True
    assert main(["--json", "verify", *args, "--suspect", clean]) == 1         # wrong suspect file
    v = json.loads(capsys.readouterr().out)
    assert not v["accepted"] and any("different" in r for r in v["reasons"])
    assert reg["commitment"]

    # SDK-05: every file of the flow matches its schema; the bundle names its verification key
    manifest = json.loads((tmp_path / "bundle" / "bundle.json").read_text())
    assert manifest["circuit"] == Z.artifacts(P.Config()).name
    pytest.importorskip("jsonschema")
    from sigil import schemas
    for name, path in (("registration", "registration.json"), ("receipt", "registration.receipt.json"),
                       ("claim", "bundle/claim.json"), ("proof", "bundle/proof.json"),
                       ("public", "bundle/public.json"), ("bundle", "bundle/bundle.json")):
        schemas.validate(name, json.loads((tmp_path / path).read_text()))

    # report: the same verification, written up; exit code follows the verdict
    assert main(["--json", "report", *args, "--suspect", model, "--out", "report.md"]) == 0
    r = json.loads(capsys.readouterr().out)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert r["accepted"] and r["checks"]["bundle_vkey_matches"] and "**Verdict: OWNERSHIP PROVEN**" in text
    assert main(["--json", "report", *args, "--suspect", clean, "--out", "bad.md"]) == 1
    capsys.readouterr()
    assert "NOT PROVEN" in (tmp_path / "bad.md").read_text(encoding="utf-8")

    # a bundle made for another verification key is rejected with its own reason
    (tmp_path / "bundle" / "bundle.json").write_text(json.dumps({**manifest, "vkey_sha256": "0" * 64}))
    assert main(["--json", "verify", *args, "--suspect", model]) == 1
    v = json.loads(capsys.readouterr().out)
    assert v["checks"]["bundle_vkey_matches"] is False
    assert "the bundle was made for a different verification key" in v["reasons"]
