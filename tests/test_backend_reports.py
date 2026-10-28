"""API-08: ownership certificates (PDF + registry-signed JSON), the compliance report (JSON + PDF) mapping
evidence to the OWASP AI Exchange #MODEL WATERMARKING text and REQUIREMENTS IDs."""
import copy
import io
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("reportlab")
pytest.importorskip("onnx")

from sigil import protocol as P  # noqa: E402
from sigil.verify import expected_public_signals  # noqa: E402

from backend.app.registry import verify_document  # noqa: E402
from backend.testing import add_user, app_client, bearer, world  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with app_client(tmp_path_factory.mktemp("reports"), auto_import_demo=True) as (app, client):
        for name, role in (("olivia", "owner"), ("victor", "verifier")):
            add_user(app, name, role)
        H = {n: bearer(client, n) for n in ("olivia", "victor")}
        app.state.snark_verifier = lambda cfg, proof, public: True
        w = world()
        client.post("/api/v2/owners", headers=H["olivia"], json={"public_key": w["owner"].public_hex, "label": "o"})
        client.post("/api/v2/models", headers=H["olivia"], files={"file": ("m.onnx", io.BytesIO(w["model"]))})
        reg = client.post("/api/v2/registrations", headers=H["olivia"], json=w["rec"]).json()
        art = client.post("/api/v2/models", headers=H["victor"],
                          files={"file": ("s.onnx", io.BytesIO(w["model"]))}).json()["artifacts"][0]
        claim = client.post("/api/v2/claims", headers=H["victor"],
                            json={"registration_id": reg["id"], "suspect_artifact_id": art["id"]}).json()
        good = expected_public_signals(w["rec"], claim["claim"], P.quantize(w["w"], w["cfg"]))
        ids = []
        for public in (good, good[:4] + ["7"]):                     # accepted, then a replay (rejected)
            pid = client.post(f"/api/v2/claims/{claim['id']}/proofs", headers=H["olivia"],
                              json={"proof": {"pi_a": ["1"]}, "public": public}).json()["id"]
            ids.append(client.post("/api/v2/verifications", headers=H["victor"], json={"proof_id": pid}).json()["id"])
        trusted = {client.get("/api/v2/registry").json()["registry_public_key"]}
        yield app, client, H, ids, trusted


def test_certificate_json_is_signed_by_the_registry(env):
    app, client, H, (ok_id, bad_id), trusted = env
    cert = client.get(f"/api/v2/verifications/{ok_id}/certificate", headers=H["olivia"]).json()
    assert cert["schema"] == "sigil.certificate/v1" and cert["verdict"] == "ACCEPTED" and cert["reasons"] == []
    assert cert["registration"]["schema"] == "sigil.registration/v2" and cert["receipt"]["registered_at"]
    assert cert["suspect_vector_source"] == "sdk_adapter" and any("theta" in s for s in cert["statements"])
    assert verify_document(cert, trusted) == []
    forged = copy.deepcopy(cert)
    forged["verdict"] = "REJECTED"
    assert "registry signature is invalid" in verify_document(forged, trusted)
    assert verify_document(cert, {"00" * 32}) == ["not signed by a trusted registry"]
    r = client.post("/api/v2/reports/verify-signature", headers=H["victor"], json={"document": cert})
    assert r.json() == {"valid": True, "problems": []}
    r = client.post("/api/v2/reports/verify-signature", headers=H["victor"], json={"document": forged})
    assert r.json()["valid"] is False

    rej = client.get(f"/api/v2/verifications/{bad_id}/certificate", headers=H["victor"]).json()
    assert rej["verdict"] == "REJECTED" and any("nonce" in r for r in rej["reasons"])
    assert verify_document(rej, trusted) == []


def test_certificate_pdf(env):
    app, client, H, (ok_id, bad_id), trusted = env
    for vid in (ok_id, bad_id):
        r = client.get(f"/api/v2/verifications/{vid}/certificate.pdf", headers=H["victor"])
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF") and r.content.rstrip().endswith(b"%%EOF") and len(r.content) > 2000
    assert client.get("/api/v2/verifications/999/certificate.pdf", headers=H["victor"]).status_code == 404


def test_compliance_report_maps_owasp_text_to_requirements(env):
    app, client, H, ids, trusted = env
    rep = client.get("/api/v2/reports/compliance", headers=H["victor"]).json()
    assert rep["schema"] == "sigil.compliance-report/v1" and verify_document(rep, trusted) == []
    items = {i["id"]: i for i in rep["items"]}
    assert set(items) == {"R1", "R2", "R3", "L1"}
    lit = (REPO / "01_Literature_Gap_Analysis.md").read_text(encoding="utf-8")
    for it in items.values():                                       # quoted verbatim from the literature review
        assert it["owasp_text"].strip(". ") in lit.replace("…", "...") or it["owasp_text"][3:40] in lit
    req = (REPO / "REQUIREMENTS.md").read_text(encoding="utf-8")
    for it in items.values():
        for rid in it["requirements"]:
            assert f"| {rid} |" in req, rid                          # every ID exists in REQUIREMENTS.md
    assert items["R2"]["status"] == "evidence" and items["R2"]["evidence"]["registry_receipts"] == 1
    assert items["R3"]["evidence"]["verifications"] == 2 and items["R3"]["evidence"]["accepted"] == 1
    assert items["R1"]["evidence"]["latest_attack_run"]["attacks"] > 0          # from the imported demo history
    assert items["L1"]["status"] == "missing"                                    # honest: not evaluated yet
    controls = {c["id"]: c for c in rep["controls"]}
    assert controls["DB-03"]["evidence"]["valid"] is True
    r = client.get("/api/v2/reports/compliance.pdf", headers=H["olivia"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
