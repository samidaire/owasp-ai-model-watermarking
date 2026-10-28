"""API-09 deployment monitoring (manual and scheduled re-checks, alerts), API-04 v2 job queue with attack runs,
DB-04 demo history import."""
import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from sqlalchemy import func, select  # noqa: E402

from backend.app import history  # noqa: E402
from backend.app.models import AttackRun, AuditEvent, ResultSnapshot  # noqa: E402
from backend.testing import add_user, app_client, bearer, use_pg, wait_until  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "demo" / "results"


@pytest.fixture
def env(tmp_path):
    (tmp_path / "deploy").mkdir()
    with app_client(tmp_path) as (app, client):
        for name, role in (("olivia", "owner"), ("victor", "verifier")):
            add_user(app, name, role)
        yield app, client, {n: bearer(client, n) for n in ("olivia", "victor")}, tmp_path / "deploy"


# ---------------------------------------------------------------------------------------------- deployments
def test_tampered_artifact_raises_an_alert(env):
    app, client, H, root = env
    model = root / "prod.onnx"
    model.write_bytes(b"\x08\x07weights v1")
    sha = hashlib.sha256(model.read_bytes()).hexdigest()
    d = client.post("/api/v2/deployments", headers=H["olivia"], json={
        "name": "mnist-prod", "environment": "production", "artifact_path": str(model), "expected_sha256": sha}).json()
    assert d["last_status"] == "pending"
    c = client.post(f"/api/v2/deployments/{d['id']}/check", headers=H["olivia"], json={}).json()
    assert c["status"] == "ok" and c["alert"] is False and c["observed_sha256"] == sha and c["registered"] is False
    assert client.get("/api/v2/deployments/alerts", headers=H["victor"]).json() == []

    model.write_bytes(b"\x08\x07weights v2 (swapped)")                      # someone replaced the deployed model
    c = client.post(f"/api/v2/deployments/{d['id']}/check", headers=H["olivia"], json={}).json()
    assert c["status"] == "mismatch" and c["alert"] is True and c["observed_sha256"] != sha
    alerts = client.get("/api/v2/deployments/alerts", headers=H["victor"]).json()
    assert [a["id"] for a in alerts] == [d["id"]] and alerts[0]["last_status"] == "mismatch"
    with app.state.sessionmaker() as db:
        last = db.scalars(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).first()
        assert last.action == "deployment.alert" and last.details["status"] == "mismatch"

    model.unlink()
    assert client.post(f"/api/v2/deployments/{d['id']}/check", headers=H["olivia"], json={}).json()["status"] == "missing"
    model.write_bytes(b"\x08\x07weights v1")                                # restored
    assert client.post(f"/api/v2/deployments/{d['id']}/check", headers=H["olivia"], json={}).json()["status"] == "ok"
    history_ = client.get(f"/api/v2/deployments/{d['id']}/checks", headers=H["victor"]).json()
    assert [h["status"] for h in history_] == ["ok", "missing", "mismatch", "ok"]
    assert client.get("/api/v2/deployments/alerts", headers=H["victor"]).json() == []
    assert client.post(f"/api/v2/deployments/{d['id']}/check", headers=H["victor"], json={}).status_code == 403


def test_deployment_paths_are_confined_and_hashes_default_to_the_artifact(env):
    app, client, H, root = env
    r = client.post("/api/v2/deployments", headers=H["olivia"], json={
        "name": "x", "environment": "e", "artifact_path": str(REPO / "README.md"), "expected_sha256": "ab" * 32})
    assert r.status_code == 422 and "deployment roots" in r.json()["detail"]
    r = client.post("/api/v2/deployments", headers=H["olivia"], json={
        "name": "x", "environment": "e", "artifact_path": "relative/path.onnx", "expected_sha256": "ab" * 32})
    assert r.status_code == 422
    r = client.post("/api/v2/deployments", headers=H["olivia"], json={
        "name": "x", "environment": "e", "artifact_path": str(root / "m.onnx")})
    assert r.status_code == 422 and "expected_sha256" in r.json()["detail"]


def test_scheduler_rechecks_in_the_background(tmp_path):
    (tmp_path / "deploy").mkdir()
    model = tmp_path / "deploy" / "edge.onnx"
    model.write_bytes(b"\x08\x07v1")
    with app_client(tmp_path, monitor_interval=0.2) as (app, client):
        add_user(app, "olivia", "owner")
        H = bearer(client, "olivia")
        d = client.post("/api/v2/deployments", headers=H, json={
            "name": "edge", "environment": "edge", "artifact_path": str(model),
            "expected_sha256": hashlib.sha256(b"\x08\x07v1").hexdigest()}).json()
        wait_until(lambda: client.get(f"/api/v2/deployments/{d['id']}", headers=H).json()["last_status"] == "ok")
        model.write_bytes(b"\x08\x07tampered")
        wait_until(lambda: client.get(f"/api/v2/deployments/{d['id']}", headers=H).json()["last_status"] == "mismatch")
        checks = client.get(f"/api/v2/deployments/{d['id']}/checks", headers=H).json()
        assert checks[0]["trigger"] == "scheduler" and checks[0]["alert"] is True
        assert app.state.monitor.runs >= 2
        # status changes are audited; unchanged scheduled checks are not (no audit spam)
        with app.state.sessionmaker() as db:
            n = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action.like("deployment.%")))
        assert n == 3                                               # created, ok, alert


# ---------------------------------------------------------------------------------------------- v2 jobs / attacks
def test_v2_attack_jobs_queue_behind_the_running_job(env):
    app, client, H, _ = env
    v1 = client.post("/api/run", json={"step": "forgery"}).json()                 # v1: a long simulated replay
    r = client.post("/api/v2/attacks/runs", headers=H["olivia"], json={"step": "attacks"})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    first = r.json()["id"]
    second = client.post("/api/v2/attacks/runs", headers=H["olivia"], json={}).json()["id"]
    assert client.post("/api/run", json={"step": "attacks"}).status_code == 409   # v1 keeps its 409
    r = client.post(f"/api/v2/jobs/{second}/cancel", headers=H["olivia"], json={})
    assert r.status_code == 202 and r.json()["status"] == "cancelled"              # cancelled before it started
    assert client.post(f"/api/jobs/{v1['id']}/cancel", json={}).status_code == 202
    wait_until(lambda: client.get(f"/api/v2/jobs/{first}", headers=H["victor"]).json()["status"] == "succeeded",
               timeout=30)
    assert client.get(f"/api/v2/jobs/{second}", headers=H["victor"]).json()["status"] == "cancelled"
    runs = client.get("/api/v2/attacks/runs", headers=H["victor"]).json()
    run = next(r for r in runs if r["job_id"] == first)
    assert run["simulated"] is True and run["total"] > 0
    detail = client.get(f"/api/v2/attacks/runs/{run['id']}", headers=H["victor"]).json()
    assert {x["family"] for x in detail["results"]} >= {"baseline", "prune"}
    jobs = client.get("/api/v2/jobs", headers=H["victor"]).json()
    assert {first, second, v1["id"]} <= {j["id"] for j in jobs}
    out = client.get(f"/api/v2/jobs/{first}", headers=H["victor"], params={"output": True}).json()["output"]
    assert out[0].startswith("[SIMULATED]")
    assert client.post(f"/api/v2/jobs/{first}/cancel", headers=H["olivia"], json={}).status_code == 409


# ---------------------------------------------------------------------------------------------- demo history
def test_import_demo_is_idempotent(env, capsys):
    app, client, H, _ = env
    present = [n for n, rel in history.RESULT_FILES.items() if (RESULTS / rel).exists()]
    with app.state.sessionmaker() as db:
        first = history.import_demo(db, RESULTS)
        second = history.import_demo(db, RESULTS)
        assert first["snapshots"] == len(present) and second == {"snapshots": 0, "attack_runs": 0}
        assert first["attack_runs"] == 1
        run = db.scalars(select(AttackRun)).first()
        rows = json.loads((RESULTS / "attacks.json").read_text())["rows"]
        assert run.source == "demo-import" and len(run.results) == len(rows)
    snaps = client.get("/api/v2/history/results", headers=H["victor"], params={"name": "train"}).json()
    assert len(snaps) == 1 and snaps[0]["path"] == "train.json" and snaps[0].get("content") is None
    full = client.get(f"/api/v2/history/results/{snaps[0]['id']}", headers=H["victor"]).json()
    assert full["content"]["commitment"] == snaps[0]["commitment"]


def test_fresh_install_imports_the_demo_history(tmp_path):
    with app_client(tmp_path, auto_import_demo=True) as (app, client):
        with app.state.sessionmaker() as db:
            assert db.scalar(select(func.count()).select_from(ResultSnapshot)) > 0
            assert db.scalar(select(func.count()).select_from(AttackRun)) == 1


def test_successful_live_run_is_snapshotted(env, tmp_path, monkeypatch):
    from backend.app import legacy
    app, client, H, _ = env
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(app.state.settings, "simulate", False)
    monkeypatch.setattr(app.state.settings, "results_dir", results)
    code = ("import json, pathlib; pathlib.Path(r'%s').joinpath('forgery.json').write_text("
            "json.dumps({'commitment': 'c1', 'threshold': 0.125}))" % results)
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", code]])
    job = client.post("/api/run", json={"step": "forgery"}).json()
    wait_until(lambda: client.get(f"/api/jobs/{job['id']}").json()["code"] == 0)

    def snap():
        with app.state.sessionmaker() as db:
            return db.scalars(select(ResultSnapshot).where(ResultSnapshot.source == f"job:{job['id']}")).first()
    s = wait_until(snap)
    assert s.name == "forgery" and s.content == {"commitment": "c1", "threshold": 0.125}


def test_cli_import_demo(tmp_path, monkeypatch, capsys):
    from backend.app import cli
    monkeypatch.setenv("SIGIL_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.main(["import-demo"]) == 0
    assert '"snapshots":' in capsys.readouterr().out
    assert cli.main(["verify-audit"]) == 0
    capsys.readouterr()
    assert cli.main(["backup", "--out", str(tmp_path / "backup.db")]) == 0
    assert (tmp_path / "backup.db").stat().st_size > 0
    capsys.readouterr()


def test_health_and_environment(env):
    app, client, H, _ = env
    assert client.get("/api/v2/health").json() == {"status": "ok", "database": "ok", "version": app.version,
                                                   "api_version": 2}
    e = client.get("/api/v2/environment", headers=H["victor"]).json()
    assert e["mode"] == "simulate" and e["database"] == ("postgresql" if use_pg() else "sqlite")
    assert e["sdk_adapters"] is True
    assert "passphrase" not in str(e).lower() and len(e["registry_public_key"]) == 64
