"""API-07 (OpenAPI export matches the app), API-10 (logs are structured and carry no secrets), DB-01
(Alembic migrations create exactly the ORM schema on an empty database)."""
import io
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("alembic")

from backend.app import logs  # noqa: E402
from backend.testing import PASSWORD, add_user, app_client, bearer  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------------------------- API-07
def test_committed_openapi_matches_the_app():
    from backend.app.cli import openapi_text
    committed = (REPO / "contract" / "openapi.json").read_text(encoding="utf-8")
    assert committed == openapi_text(), "run: python -m backend.app.cli export-openapi"


def test_every_v2_operation_is_documented():
    from backend.app.cli import openapi_document
    spec = openapi_document()
    assert "Problem" in spec["components"]["schemas"] and "HTTPBearer" in spec["components"]["securitySchemes"]
    v2 = {p: ops for p, ops in spec["paths"].items() if p.startswith("/api/v2/")}
    assert len(v2) >= 40
    for path, ops in v2.items():
        for method, op in ops.items():
            assert op.get("summary") and op.get("tags"), (method, path)
            if path not in ("/api/v2/health", "/api/v2/registry", "/api/v2/auth/login"):
                assert "401" in op["responses"], (method, path)
    assert {"/api/state", "/api/steps", "/api/run", "/api/jobs/{job_id}", "/api/jobs/{job_id}/stream",
            "/api/jobs/{job_id}/cancel"} <= set(spec["paths"])


# ---------------------------------------------------------------------------------------------- API-10
def test_redaction():
    text = ('login password="hunter2 pass" token=sgl_abcdefghijklmnop Authorization: Bearer sgl_xyzxyzxyzxyz '
            "-----BEGIN PRIVATE KEY-----\nMIIabc\n-----END PRIVATE KEY----- $argon2id$v=19$m=65536$salt$hash "
            '{"seed": "123456789", "passphrase": "s3cret"}')
    out = logs.redact(text)
    for secret in ("hunter2", "sgl_abcdefghijklmnop", "sgl_xyzxyzxyzxyz", "MIIabc", "salt$hash", "123456789", "s3cret"):
        assert secret not in out, secret


def test_logs_are_json_and_never_contain_secrets(tmp_path):
    buf = io.StringIO()
    with app_client(tmp_path, registry_passphrase="registry-passphrase-XYZ") as (app, client):
        logs.configure("DEBUG", True, stream=buf)
        add_user(app, "olivia", "owner")
        h = bearer(client, "olivia")
        token = h["Authorization"].split()[1]
        client.get("/api/v2/auth/me", headers=h)
        client.post("/api/v2/auth/login", json={"username": "olivia", "password": "wrong-password-123"})
        client.get(f"/api/v2/owners?token={token}", headers=h)           # a secret in a query string
        logs.log.info("debug dump %s", {"password": PASSWORD, "Authorization": f"Bearer {token}"})
        try:
            raise ValueError(f"boom with {token}")
        except ValueError:
            logs.log.exception("failure")
    text = buf.getvalue()
    lines = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert lines and all({"ts", "level", "logger", "msg"} <= set(r) for r in lines)
    assert any(r.get("path") == "/api/v2/owners" and r.get("status") == 200 for r in lines)
    for secret in (PASSWORD, "wrong-password-123", token, "registry-passphrase-XYZ", "$argon2id$v"):
        assert secret not in text, secret


# ---------------------------------------------------------------------------------------------- DB-01
def _diff(engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from backend.app.models import Base
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        return [d for d in compare_metadata(ctx, Base.metadata)]


def test_migrations_create_exactly_the_orm_schema(tmp_path):
    from alembic import command
    from sqlalchemy import inspect

    from backend.app.db import alembic_config, make_engine, run_migrations
    from backend.testing import database
    with database() as url:
        url = url or f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
        engine = make_engine(url)
        run_migrations(engine)
        names = set(inspect(engine).get_table_names())
        assert {"users", "owners", "models", "model_artifacts", "watermark_configs", "registrations", "receipts",
                "embeddings", "claims", "proofs", "verifications", "attack_runs", "attack_results", "deployments",
                "deployment_checks", "jobs", "job_logs", "audit_events", "result_snapshots", "api_tokens"} <= names
        assert _diff(engine) == []
        cfg = alembic_config()
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        run_migrations(engine)                                       # and back up again
        assert _diff(engine) == []
        engine.dispose()
