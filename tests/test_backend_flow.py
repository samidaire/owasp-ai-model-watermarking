"""API-03, CR-03, ZK-06 through the API: owner key -> upload -> signed registration -> registry receipt ->
verifier claim -> proof bundle -> verification with named reasons; the dispute rule; the real Groth16 proof
when the circuit is set up (SIGIL_CIRCUITS with build/*.zkey), else skipped.

Most tests inject a SNARK verifier (app.state.snark_verifier) so every *other* check of
sigil.verify.verify_ownership is exercised for real: the suspect's vector is recomputed from the uploaded
ONNX file by sigil.adapters.
"""
import copy
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("onnx")

from sigil import protocol as P  # noqa: E402
from sigil.records import make_registration, verify_receipt  # noqa: E402
from sigil.verify import expected_public_signals  # noqa: E402

from backend.testing import add_user, app_client, bearer, onnx_model_bytes, world  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FAKE_PROOF = {"pi_a": ["1", "2", "1"], "pi_b": [["1", "2"], ["3", "4"], ["1", "0"]], "pi_c": ["5", "6", "1"],
              "protocol": "groth16", "curve": "bn128"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with app_client(tmp_path_factory.mktemp("flow")) as (app, client):
        for name, role in (("olivia", "owner"), ("mallory", "owner"), ("victor", "verifier"), ("ada", "admin")):
            add_user(app, name, role)
        heads = {n: bearer(client, n) for n in ("olivia", "mallory", "victor", "ada")}
        yield app, client, heads


@pytest.fixture
def snark_ok(env, monkeypatch):
    monkeypatch.setattr(env[0].state, "snark_verifier", lambda cfg, proof, public: True, raising=False)


def upload(client, headers, data: bytes, name="model.onnx", purpose=None):
    form = {"purpose": purpose} if purpose else {}
    return client.post("/api/v2/models", headers=headers, files={"file": (name, io.BytesIO(data))}, data=form)


def register(client, H, w, who="olivia"):
    """Owner key + upload + registration; returns the registration JSON from the API."""
    r = client.post("/api/v2/owners", headers=H[who], json={"public_key": w["owner"].public_hex, "label": who})
    assert r.status_code in (201, 409), r.text
    assert upload(client, H[who], w["model"]).status_code == 201
    r = client.post("/api/v2/registrations", headers=H[who], json=w["rec"])
    assert r.status_code == 201, r.text
    return r.json()


def claim_for(client, H, reg_id, suspect: bytes):
    r = upload(client, H["victor"], suspect, "suspect.onnx")
    assert r.status_code == 201, r.text
    art = r.json()["artifacts"][0]
    assert r.json()["purpose"] == "suspect"
    r = client.post("/api/v2/claims", headers=H["victor"], json={"registration_id": reg_id, "suspect_artifact_id": art["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def signals(w, claim, vector=None):
    return expected_public_signals(w["rec"], claim["claim"], P.quantize(w["w"] if vector is None else vector, w["cfg"]))


def submit_and_verify(client, H, claim, public, proof=FAKE_PROOF, **extra):
    r = client.post(f"/api/v2/claims/{claim['id']}/proofs", headers=H["olivia"], json={"proof": proof, "public": public})
    assert r.status_code == 201, r.text
    r = client.post("/api/v2/verifications", headers=H["victor"], json={"proof_id": r.json()["id"], **extra})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------------------------- happy path
def test_owner_proof_accepted_and_receipt_verifies(env, snark_ok):
    app, client, H = env
    w = world()
    reg = register(client, H, w)
    assert reg["registration"] == w["rec"] and reg["model_sha256"] == w["sha"] and reg["model_artifact_id"]
    trusted = {client.get("/api/v2/registry").json()["registry_public_key"]}
    assert verify_receipt(reg["receipt"], w["rec"], trusted) == []           # CR-03: registry timestamp
    claim = claim_for(client, H, reg["id"], w["model"])                        # the stolen copy, unchanged
    assert claim["claim"]["suspect_model_sha256"] == w["sha"] and claim["opened_at"] > reg["registered_at"]
    v = submit_and_verify(client, H, claim, signals(w, claim))
    assert v["accepted"] is True and v["reasons"] == [], v
    assert v["vector_source"] == "sdk_adapter" and v["suspect_sha256"] == w["sha"]
    assert all(v["checks"].values()) and v["checks"]["public_w_hash"] and v["checks"]["snark_valid"]
    got = client.get(f"/api/v2/verifications/{v['id']}", headers=H["olivia"]).json()
    assert got == v
    bundle = client.get(f"/api/v2/proofs/{v['proof_id']}/bundle", headers=H["victor"]).json()
    assert bundle["claim.json"] == claim["claim"] and bundle["registration.json"] == w["rec"]


def test_rejections_carry_named_reasons(env, snark_ok, monkeypatch):
    app, client, H = env
    w = world()
    reg = register(client, H, w)
    claim = claim_for(client, H, reg["id"], w["model"])

    replay = list(signals(w, claim))
    replay[4] = str(int(replay[4]) ^ 1)                                         # another claim's nonce
    v = submit_and_verify(client, H, claim, replay)
    assert not v["accepted"] and any("nonce mismatch" in r for r in v["reasons"])

    other = w["w"].copy()
    other[0] += 0.01                                                            # proof about a different model
    v = submit_and_verify(client, H, claim, signals(w, claim, other))
    assert not v["accepted"] and any("different model" in r for r in v["reasons"])

    monkeypatch.setattr(app.state, "snark_verifier", lambda cfg, proof, public: False)
    v = submit_and_verify(client, H, claim, signals(w, claim))
    assert not v["accepted"] and v["reasons"] == ["the zk-SNARK does not verify"]

    r = client.post(f"/api/v2/claims/{claim['id']}/proofs", headers=H["olivia"],
                    json={"proof": FAKE_PROOF, "public": signals(w, claim)[:4]})
    assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json"


def test_suspect_is_another_model(env, snark_ok):
    """The claim is about a different (fine-tuned) file: the owner's proof for the original doesn't transfer."""
    app, client, H = env
    w = world()
    reg = register(client, H, w)
    tuned = w["w"].copy()
    tuned[:5] += 0.001                                                          # ~65 quantisation steps
    claim = claim_for(client, H, reg["id"], onnx_model_bytes(tuned))
    v = submit_and_verify(client, H, claim, signals(w, claim))                  # w_hash of the original
    assert not v["accepted"] and any("w_hash mismatch" in r for r in v["reasons"])


def test_missing_zk_toolchain_is_a_named_reason(env, monkeypatch, tmp_path):
    app, client, H = env
    monkeypatch.setattr(app.state, "snark_verifier", None, raising=False)
    monkeypatch.setenv("SIGIL_CIRCUITS", str(tmp_path))                       # no ownership.circom here
    w = world()
    reg = register(client, H, w)
    claim = claim_for(client, H, reg["id"], w["model"])
    v = submit_and_verify(client, H, claim, signals(w, claim))
    assert not v["accepted"] and v["checks"]["snark_valid"] is False
    assert any(r.startswith("the zk-SNARK was not checked") for r in v["reasons"])


def test_vector_fallback_without_adapters(env, snark_ok, monkeypatch):
    """TODO(M4) path: without sigil.adapters the request must carry the vector; it's flagged as such."""
    app, client, H = env
    w = world()
    reg = register(client, H, w)
    claim = claim_for(client, H, reg["id"], w["model"])
    monkeypatch.setitem(sys.modules, "sigil.adapters", None)                   # import -> ImportError
    r = client.post(f"/api/v2/claims/{claim['id']}/proofs", headers=H["olivia"],
                    json={"proof": FAKE_PROOF, "public": signals(w, claim)})
    pid = r.json()["id"]
    r = client.post("/api/v2/verifications", headers=H["victor"], json={"proof_id": pid})
    assert r.status_code == 422 and "suspect_vector is required" in r.json()["detail"]
    r = client.post("/api/v2/verifications", headers=H["victor"], json={"proof_id": pid, "suspect_vector": list(w["w"])})
    v = r.json()
    assert r.status_code == 201 and v["vector_source"] == "request" and v["checks"]["suspect_vector_from_file"] is False


def test_proof_bundle_upload_as_files(env, snark_ok):
    app, client, H = env
    w = world()
    reg = register(client, H, w)
    claim = claim_for(client, H, reg["id"], w["model"])
    files = {"proof": ("proof.json", json.dumps(FAKE_PROOF)), "public": ("public.json", json.dumps(signals(w, claim))),
             "claim": ("claim.json", json.dumps(claim["claim"]))}
    r = client.post(f"/api/v2/claims/{claim['id']}/proofs/upload", headers=H["olivia"], files=files)
    assert r.status_code == 201, r.text
    wrong = dict(files, claim=("claim.json", json.dumps({**claim["claim"], "nonce": "1"})))
    r = client.post(f"/api/v2/claims/{claim['id']}/proofs/upload", headers=H["olivia"], files=wrong)
    assert r.status_code == 422 and "not this claim" in r.json()["detail"]
    r = client.post(f"/api/v2/claims/{claim['id']}/proofs/upload", headers=H["olivia"],
                    files={"proof": ("proof.json", "{nope"), "public": ("public.json", "[]")})
    assert r.status_code == 422


# ---------------------------------------------------------------------------------------------- registry rules
def test_registration_validation(env):
    app, client, H = env
    w = world()
    client.post("/api/v2/owners", headers=H["olivia"], json={"public_key": w["owner"].public_hex, "label": "o"})
    bad = copy.deepcopy(w["rec"])
    bad["model_sha256"] = "cd" * 32                                             # breaks the owner signature
    r = client.post("/api/v2/registrations", headers=H["olivia"], json=bad)
    assert r.status_code == 422 and "owner signature is invalid" in r.json()["problems"]
    r = client.post("/api/v2/registrations", headers=H["olivia"], json={**w["rec"], "seed": "123"})
    assert r.status_code == 422                                                  # unknown fields are refused
    stranger = world()["rec"]                                                    # owner key never registered
    r = client.post("/api/v2/registrations", headers=H["olivia"], json=stranger)
    assert r.status_code == 422 and "register this owner public key first" in r.json()["detail"]
    r = client.post("/api/v2/registrations", headers=H["mallory"], json=w["rec"])
    assert r.status_code == 403                                                  # someone else's owner key
    assert client.post("/api/v2/registrations", headers=H["olivia"], json=w["rec"]).status_code == 201
    assert client.post("/api/v2/registrations", headers=H["olivia"], json=w["rec"]).status_code == 409


def test_owner_keys_are_public_only(env):
    app, client, H = env
    pk = world()["owner"].public_hex
    r = client.post("/api/v2/owners", headers=H["olivia"], json={"public_key": pk, "label": "x", "private_key": "00" * 32})
    assert r.status_code == 422
    r = client.post("/api/v2/owners", headers=H["olivia"], json={"public_key": "zz" * 32, "label": "x"})
    assert r.status_code == 422
    r = client.post("/api/v2/owners", headers=H["olivia"], json={"public_key": pk, "label": "x"})
    assert r.status_code == 201 and r.json()["pk_hash"] == str(P.pk_hash(bytes.fromhex(pk)))
    assert client.post("/api/v2/owners", headers=H["olivia"], json={"public_key": pk, "label": "y"}).status_code == 409


def test_dispute_rule_earliest_registration_wins(env):
    """CR-03: owner registers first; the thief re-registers the same model with their own key later."""
    import time
    app, client, H = env
    w = world()
    reg_owner = register(client, H, w)
    time.sleep(1.1)                                                              # receipts have 1 s resolution
    thief = world()
    rec_thief = make_registration(thief["owner"], thief["seed"], thief["cfg"], w["sha"])
    client.post("/api/v2/owners", headers=H["mallory"], json={"public_key": thief["owner"].public_hex, "label": "m"})
    r = client.post("/api/v2/registrations", headers=H["mallory"], json=rec_thief)
    assert r.status_code == 201
    reg_thief = r.json()
    assert reg_thief["registered_at"] > reg_owner["registered_at"]
    r = client.get("/api/v2/registrations/earliest", headers=H["victor"], params={"model_sha256": w["sha"]})
    assert r.status_code == 200 and r.json()["candidates"] == 2
    assert r.json()["winner"]["id"] == reg_owner["id"]
    lst = client.get("/api/v2/registrations", headers=H["victor"], params={"model_sha256": w["sha"]}).json()
    assert {x["id"] for x in lst} == {reg_owner["id"], reg_thief["id"]}


def test_claims_and_proofs_respect_roles(env, snark_ok):
    app, client, H = env
    w = world()
    reg = register(client, H, w)
    r = client.post("/api/v2/claims", headers=H["olivia"], json={"registration_id": reg["id"], "suspect_artifact_id": 1})
    assert r.status_code == 403                                                  # owners don't open claims
    claim = claim_for(client, H, reg["id"], w["model"])
    r = client.post(f"/api/v2/claims/{claim['id']}/proofs", headers=H["mallory"],
                    json={"proof": FAKE_PROOF, "public": signals(w, claim)})
    assert r.status_code == 403                                                  # not mallory's registration
    r = client.post(f"/api/v2/claims/{claim['id']}/proofs", headers=H["victor"],
                    json={"proof": FAKE_PROOF, "public": signals(w, claim)})
    assert r.status_code == 403                                                  # verifiers don't submit proofs
    r = client.post("/api/v2/verifications", headers=H["olivia"], json={"proof_id": 1})
    assert r.status_code == 403                                                  # owners don't verify
    assert client.get(f"/api/v2/claims/{claim['id']}", headers=H["olivia"]).json()["nonce"] == claim["nonce"]


# ---------------------------------------------------------------------------------------------- real Groth16
def _zk_ready():
    try:
        from sigil.zk import circom as Z
        a = Z.artifacts(P.Config())
        return a.zkey.exists() and a.wasm.exists() and a.vkey.exists() and shutil.which("node") is not None
    except Exception:  # noqa: BLE001 - toolchain missing
        return False


@pytest.mark.zk
@pytest.mark.slow
@pytest.mark.skipif(not _zk_ready(), reason="Groth16 setup for the demo config not found (set SIGIL_CIRCUITS)")
def test_real_groth16_proof_end_to_end(tmp_path):
    """Demo F's identities (public demo passphrase) prove ownership of demo/ckpt/v2/watermarked_v2.pt for a
    claim the backend opened; the backend verifies with SnarkJS and the SDK adapters (no injection)."""
    pytest.importorskip("torch")
    from sigil import adapters, secretbox
    from sigil.identity import KeyPair
    from sigil.zk import circom as Z
    v2 = REPO / "demo" / "ckpt" / "v2"
    passphrase = "sigil-demo-only-passphrase"                                   # PUBLIC demo value (README)
    owner = KeyPair.load(v2 / "owner.key", passphrase)
    seed = int(secretbox.load(v2 / "seed.json", passphrase, "seed")["seed"])
    rec = json.loads((v2 / "registration.json").read_text())
    cfg = P.Config.from_dict(rec["config"])
    model = (v2 / "watermarked_v2.pt").read_bytes()
    assert hashlib.sha256(model).hexdigest() == rec["model_sha256"]
    with app_client(tmp_path) as (app, client):
        add_user(app, "olivia", "owner")
        add_user(app, "victor", "verifier")
        H = {"olivia": bearer(client, "olivia"), "victor": bearer(client, "victor")}
        assert client.post("/api/v2/owners", headers=H["olivia"],
                           json={"public_key": owner.public_hex, "label": "demo F"}).status_code == 201
        assert upload(client, H["olivia"], model, "watermarked_v2.pt").status_code == 201
        reg = client.post("/api/v2/registrations", headers=H["olivia"], json=rec).json()
        r = upload(client, H["victor"], model, "suspect.pt")
        claim = client.post("/api/v2/claims", headers=H["victor"],
                            json={"registration_id": reg["id"], "suspect_artifact_id": r.json()["artifacts"][0]["id"]}).json()
        w_q = adapters.quantized_vector(v2 / "watermarked_v2.pt", cfg)
        proof, public, _ = Z.prove(cfg, P.circuit_input(seed, w_q, P.pk_hash(owner.public_bytes), cfg, int(claim["nonce"])))
        v = submit_and_verify(client, H, claim, public, proof=proof)
        assert v["accepted"] is True and v["checks"]["snark_valid"] is True and v["vector_source"] == "sdk_adapter", v
        bad = copy.deepcopy(proof)
        bad["pi_a"][0] = str(int(bad["pi_a"][0]) + 1)
        v = submit_and_verify(client, H, claim, public, proof=bad)
        assert not v["accepted"] and "the zk-SNARK does not verify" in v["reasons"]
