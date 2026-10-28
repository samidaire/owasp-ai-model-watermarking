"""DB-03: the append-only, hash-chained audit log. Every state-changing call writes one event; tampering
(even with the triggers dropped) is detected; exports carry a verifiable chain proof."""
import io
import json
import threading

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("onnx")

from sqlalchemy import func, select, text  # noqa: E402

from backend.app import audit  # noqa: E402
from backend.app.models import AuditEvent  # noqa: E402
from backend.app.registry import verify_document  # noqa: E402
from backend.testing import add_user, app_client, bearer, world  # noqa: E402


@pytest.fixture
def env(tmp_path):
    with app_client(tmp_path) as (app, client):
        for name, role in (("olivia", "owner"), ("victor", "verifier"), ("ada", "admin")):
            add_user(app, name, role)
        yield app, client, {n: bearer(client, n) for n in ("olivia", "victor", "ada")}


def count(app) -> int:
    with app.state.sessionmaker() as db:
        return db.scalar(select(func.count()).select_from(AuditEvent))


def last_action(app) -> str:
    with app.state.sessionmaker() as db:
        return db.scalars(select(AuditEvent.action).order_by(AuditEvent.seq.desc()).limit(1)).first()


def actions_after(app, n: int) -> list[str]:
    with app.state.sessionmaker() as db:
        return list(db.scalars(select(AuditEvent.action).where(AuditEvent.seq > n).order_by(AuditEvent.seq)))


def test_every_state_changing_call_writes_an_event(env, tmp_path, monkeypatch):
    app, client, H = env
    monkeypatch.setattr(app.state, "snark_verifier", lambda *a: True, raising=False)
    w = world()
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "m.onnx").write_bytes(w["model"])
    state = {}

    def step(name, fn, action):
        before = count(app)
        r = fn()
        assert r.status_code < 300, (name, r.text)
        assert action in actions_after(app, before), name        # a job thread may add job.finished too
        return r.json() if r.content else None

    o = step("owner", lambda: client.post("/api/v2/owners", headers=H["olivia"],
                                          json={"public_key": w["owner"].public_hex, "label": "o"}), "owner.registered")
    m = step("upload", lambda: client.post("/api/v2/models", headers=H["olivia"],
                                           files={"file": ("m.onnx", io.BytesIO(w["model"]))}), "model.uploaded")
    reg = step("registration", lambda: client.post("/api/v2/registrations", headers=H["olivia"], json=w["rec"]),
               "registration.created")
    s = step("suspect", lambda: client.post("/api/v2/models", headers=H["victor"],
                                            files={"file": ("s.onnx", io.BytesIO(w["model"]))}), "model.uploaded")
    c = step("claim", lambda: client.post("/api/v2/claims", headers=H["victor"], json={
        "registration_id": reg["id"], "suspect_artifact_id": s["artifacts"][0]["id"]}), "claim.opened")
    p = step("proof", lambda: client.post(f"/api/v2/claims/{c['id']}/proofs", headers=H["olivia"],
                                          json={"proof": {"pi_a": []}, "public": ["1"] * 5}), "proof.submitted")
    step("verify", lambda: client.post("/api/v2/verifications", headers=H["victor"], json={"proof_id": p["id"]}),
         "verification.completed")
    d = step("deployment", lambda: client.post("/api/v2/deployments", headers=H["olivia"], json={
        "name": "prod", "environment": "test", "artifact_path": str(tmp_path / "deploy" / "m.onnx"),
        "model_artifact_id": m["artifacts"][0]["id"]}), "deployment.created")
    step("check", lambda: client.post(f"/api/v2/deployments/{d['id']}/check", headers=H["olivia"], json={}),
         "deployment.check")
    step("patch deployment", lambda: client.patch(f"/api/v2/deployments/{d['id']}", headers=H["olivia"],
                                                  json={"active": False}), "deployment.updated")
    t = step("token", lambda: client.post("/api/v2/auth/tokens", headers=H["olivia"], json={"name": "x"}),
             "auth.token_created")
    step("revoke", lambda: client.delete(f"/api/v2/auth/tokens/{t['token_id']}", headers=H["olivia"]),
         "auth.token_revoked")
    u = step("user", lambda: client.post("/api/v2/users", headers=H["ada"], json={
        "username": "zed", "password": "a long password", "role": "owner"}), "user.created")
    step("user patch", lambda: client.patch(f"/api/v2/users/{u['id']}", headers=H["ada"], json={"role": "verifier"}),
         "user.updated")
    step("login", lambda: client.post("/api/v2/auth/login", json={"username": "zed", "password": "a long password"}),
         "auth.login")
    job = step("v1 run", lambda: client.post("/api/run", json={"step": "forgery"}), "demo.run")
    step("v1 cancel", lambda: client.post(f"/api/jobs/{job['id']}/cancel", json={}), "demo.cancel")
    state["chain"] = client.get("/api/v2/audit/verify", headers=H["ada"]).json()
    assert state["chain"]["valid"] and state["chain"]["count"] == count(app)
    assert client.post("/api/v2/auth/login", json={"username": "zed", "password": "nope"}).status_code == 401
    assert last_action(app) == "auth.login_failed" and o["id"]


def test_chain_hashes_are_sha256_of_prev_and_event(env):
    app, client, H = env
    events = client.get("/api/v2/audit/events", headers=H["victor"]).json()
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    prev = "0" * 64
    for e in events:
        assert e["prev_hash"] == prev and e["hash"] == audit.chain_hash(prev, e["event_json"])
        assert json.loads(e["event_json"])["action"] == e["action"]
        prev = e["hash"]
    assert client.get("/api/v2/audit/events", headers=H["olivia"]).status_code == 403


def test_append_only_triggers(env):
    app, _, _ = env
    with app.state.sessionmaker() as db:
        for stmt in ("UPDATE audit_events SET actor = 'x' WHERE seq = 1", "DELETE FROM audit_events WHERE seq = 1"):
            with pytest.raises(Exception, match="append-only"):
                db.execute(text(stmt))
                db.commit()
            db.rollback()
    with app.state.sessionmaker() as db:
        assert audit.verify_chain(db)["valid"]


def _drop_triggers(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
    else:
        db.execute(text("DROP TRIGGER audit_events_no_update"))
        db.execute(text("DROP TRIGGER audit_events_no_delete"))


@pytest.mark.parametrize("tamper,expected", [
    ("UPDATE audit_events SET actor = 'user:mallory' WHERE seq = 2", "stored columns differ"),
    ("UPDATE audit_events SET event_json = replace(event_json, 'victor', 'mallory') WHERE seq = 2", "hash does not match"),
    ("DELETE FROM audit_events WHERE seq = 2", "sequence gap"),
])
def test_tampered_rows_are_detected(env, tamper, expected):
    """A DBA who bypasses the triggers still can't change history unnoticed."""
    app, client, H = env
    with app.state.sessionmaker() as db:
        _drop_triggers(db)
        db.execute(text(tamper))
        db.commit()
    r = client.get("/api/v2/audit/verify", headers=H["victor"]).json()
    assert r["valid"] is False and any(expected in p["problem"] for p in r["problems"]), r
    assert any(p["seq"] in (2, 3) for p in r["problems"])


def test_a_rewritten_chain_is_caught_by_a_signed_head(env):
    app, client, H = env
    head = client.get("/api/v2/audit/head", headers=H["victor"]).json()
    trusted = {client.get("/api/v2/registry").json()["registry_public_key"]}
    assert verify_document(head, trusted) == []
    with app.state.sessionmaker() as db:                       # rewrite every event and recompute every hash
        _drop_triggers(db)
        rows = db.scalars(select(AuditEvent).order_by(AuditEvent.seq)).all()
        prev = audit.GENESIS
        for row in rows:
            ev = json.loads(row.event_json)
            if row.seq == 1:
                ev["actor"] = row.actor = "user:mallory"
            row.event_json = audit.canonical(ev)
            row.prev_hash, row.hash = prev, audit.chain_hash(prev, row.event_json)
            prev = row.hash
        db.commit()
    assert client.get("/api/v2/audit/verify", headers=H["victor"]).json()["valid"] is True     # internally consistent
    r = client.get("/api/v2/audit/verify", headers=H["victor"],
                   params={"anchor_seq": head["head_seq"], "anchor_hash": head["head_hash"]}).json()
    assert r["valid"] is False and r["anchor_ok"] is False


def test_exports_carry_a_verifiable_chain_proof(env, tmp_path, capsys):
    from backend.app import cli
    from backend.app.reports import verify_audit_csv
    app, client, H = env
    trusted = {client.get("/api/v2/registry").json()["registry_public_key"]}
    doc = client.get("/api/v2/audit/export", headers=H["victor"]).json()
    assert doc["schema"] == "sigil.audit-export/v1" and doc["chain"]["valid"] and verify_document(doc, trusted) == []
    assert audit.verify_events(doc["events"])["valid"]
    forged = json.loads(json.dumps(doc))
    forged["events"][0]["actor"] = "someone else"
    assert verify_document(forged, trusted) and not audit.verify_events(forged["events"])["valid"]
    r = client.get("/api/v2/audit/export", headers=H["victor"], params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert verify_audit_csv(r.text)["valid"]
    head = json.loads(r.headers["x-sigil-chain-head"])
    assert verify_document(head, trusted) == [] and head["head_hash"] == verify_audit_csv(r.text)["head_hash"]
    p = tmp_path / "export.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main(["verify-audit", "--export", str(p)]) == 0
    p.write_text(json.dumps(forged), encoding="utf-8")
    assert cli.main(["verify-audit", "--export", str(p)]) == 1
    capsys.readouterr()


def test_concurrent_appends_never_fork_the_chain(env):
    app, _, _ = env
    errors = []

    def worker(i):
        try:
            for j in range(5):
                with app.state.sessionmaker() as db:
                    audit.append(db, f"test:{i}", "test.concurrent", "test", f"{i}-{j}", {"i": i, "j": j})
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with app.state.sessionmaker() as db:
        status = audit.verify_chain(db)
        assert status["valid"] and status["count"] == status["head_seq"]
