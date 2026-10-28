"""DB-01 on real PostgreSQL 16 (embedded via the `pgserver` wheel; skipped when it isn't installed).

    pytest -m pg tests/test_backend_pg.py                 # just these
    SIGIL_TEST_DB=pg pytest tests/test_backend_*.py       # the whole backend suite on PostgreSQL
"""
import contextlib
import io
import threading

import pytest

pytest.importorskip("fastapi")
from backend.testing import pg_available  # noqa: E402

pytestmark = [pytest.mark.pg,
              pytest.mark.skipif(not pg_available(), reason="pgserver/psycopg not installed (embedded PostgreSQL)")]

from sqlalchemy import inspect, text  # noqa: E402

from backend.app import audit  # noqa: E402
from backend.app.db import make_engine, make_sessionmaker, run_migrations  # noqa: E402
from backend.testing import add_user, app_client, bearer, database, world  # noqa: E402


@pytest.fixture(scope="module")
def engine():
    with database(force_pg=True) as url:
        eng = make_engine(url)
        run_migrations(eng)                                       # alembic upgrade head on an empty database
        yield eng
        eng.dispose()


def test_postgres_16_with_the_alembic_schema(engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from backend.app.models import Base
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar()
        assert version.startswith("16."), version
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"
        assert compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata) == []
    cols = {c["name"]: c for c in inspect(engine).get_columns("audit_events")}
    assert cols["details"]["type"].__class__.__name__ == "JSONB"


def test_append_only_on_postgres(engine):
    sm = make_sessionmaker(engine)
    with sm() as db:
        audit.append(db, "test", "pg.test", details={"x": 1.5})
    for stmt in ("UPDATE audit_events SET actor = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
        with sm() as db, pytest.raises(Exception, match="append-only"):
            db.execute(text(stmt))
            db.commit()
    with sm() as db:
        assert audit.verify_chain(db)["valid"]


def test_advisory_lock_serialises_appends_across_engines(engine, monkeypatch):
    """With the in-process lock disabled (as between two server processes), PostgreSQL's advisory lock alone
    keeps the chain linear."""
    monkeypatch.setattr(audit, "_LOCK", contextlib.nullcontext())
    engines = [make_engine(engine.url.render_as_string(hide_password=False)) for _ in range(4)]
    errors = []

    def worker(eng, i):
        sm = make_sessionmaker(eng)
        try:
            for j in range(10):
                with sm() as db:
                    audit.append(db, f"proc:{i}", "pg.concurrent", "test", f"{i}-{j}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=worker, args=(e, i)) for i, e in enumerate(engines)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for e in engines:
        e.dispose()
    assert not errors
    with make_sessionmaker(engine)() as db:
        status = audit.verify_chain(db)
    assert status["valid"] and status["count"] == status["head_seq"]


def test_end_to_end_flow_on_postgres(tmp_path):
    from sigil import protocol as P
    from sigil.verify import expected_public_signals
    with app_client(tmp_path, force_pg=True, auto_import_demo=True) as (app, client):
        assert app.state.engine.dialect.name == "postgresql"
        app.state.snark_verifier = lambda cfg, proof, public: True
        add_user(app, "olivia", "owner")
        add_user(app, "victor", "verifier")
        H = {n: bearer(client, n) for n in ("olivia", "victor")}
        w = world()
        assert client.post("/api/v2/owners", headers=H["olivia"],
                           json={"public_key": w["owner"].public_hex, "label": "o"}).status_code == 201
        reg = client.post("/api/v2/registrations", headers=H["olivia"], json=w["rec"]).json()
        art = client.post("/api/v2/models", headers=H["victor"],
                          files={"file": ("s.onnx", io.BytesIO(w["model"]))}).json()["artifacts"][0]
        claim = client.post("/api/v2/claims", headers=H["victor"],
                            json={"registration_id": reg["id"], "suspect_artifact_id": art["id"]}).json()
        public = expected_public_signals(w["rec"], claim["claim"], P.quantize(w["w"], w["cfg"]))
        pid = client.post(f"/api/v2/claims/{claim['id']}/proofs", headers=H["olivia"],
                          json={"proof": {"pi_a": ["1"]}, "public": public}).json()["id"]
        v = client.post("/api/v2/verifications", headers=H["victor"], json={"proof_id": pid}).json()
        assert v["accepted"] is True, v
        job = client.post("/api/run", json={"step": "forgery"}).json()
        assert client.post(f"/api/jobs/{job['id']}/cancel", json={}).status_code == 202
        assert client.get("/api/v2/audit/verify", headers=H["victor"]).json()["valid"] is True
        rep = client.get("/api/v2/reports/compliance", headers=H["victor"]).json()
        assert rep["items"][0]["evidence"]["latest_attack_run"]["attacks"] > 0
