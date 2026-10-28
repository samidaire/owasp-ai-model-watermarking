"""API-06: local accounts (Argon2id), per-user bearer tokens, roles; the create-admin CLI."""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from backend.testing import PASSWORD, add_user, app_client, bearer  # noqa: E402


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with app_client(tmp_path_factory.mktemp("auth")) as (app, client):
        for name, role in (("olivia", "owner"), ("victor", "verifier"), ("ada", "admin")):
            add_user(app, name, role)
        yield app, client, {n: bearer(client, n) for n in ("olivia", "victor", "ada")}


def test_passwords_are_argon2id_and_tokens_are_stored_hashed(env):
    from sqlalchemy import select

    from backend.app.models import ApiToken, User
    app, client, H = env
    with app.state.sessionmaker() as db:
        u = db.scalar(select(User).where(User.username == "olivia"))
        assert u.password_hash.startswith("$argon2id$") and PASSWORD not in u.password_hash
    r = client.post("/api/v2/auth/login", json={"username": "olivia", "password": PASSWORD, "token_name": "laptop"})
    token = r.json()["token"]
    assert token.startswith("sgl_") and r.json()["user"]["role"] == "owner" and r.json()["expires_at"]
    with app.state.sessionmaker() as db:
        row = db.get(ApiToken, r.json()["token_id"])
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest() and token not in row.prefix + row.token_hash
    assert client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["username"] == "olivia"


def test_bad_credentials(env):
    app, client, H = env
    for body in ({"username": "olivia", "password": "wrong password"}, {"username": "nobody", "password": PASSWORD}):
        r = client.post("/api/v2/auth/login", json=body)
        assert r.status_code == 401 and r.json()["detail"] == "wrong username or password"
    for h in ({}, {"Authorization": "Bearer sgl_not-a-token"}, {"Authorization": "Basic b2xpdmlhOng="},
              {"Authorization": "Bearer "}, {"Authorization": "Token abc"}):
        assert client.get("/api/v2/auth/me", headers=h).status_code == 401, h


def test_token_lifecycle(env):
    from backend.app.models import ApiToken
    app, client, H = env
    r = client.post("/api/v2/auth/tokens", headers=H["olivia"], json={"name": "ci", "ttl_days": 1})
    assert r.status_code == 201
    tok, tid = r.json()["token"], r.json()["token_id"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/v2/auth/me", headers=h).status_code == 200
    names = [t["name"] for t in client.get("/api/v2/auth/tokens", headers=H["olivia"]).json()]
    assert "ci" in names and all("token" not in t for t in client.get("/api/v2/auth/tokens", headers=h).json())
    assert client.delete(f"/api/v2/auth/tokens/{tid}", headers=H["victor"]).status_code == 404   # not victor's
    assert client.delete(f"/api/v2/auth/tokens/{tid}", headers=h).status_code == 204
    assert client.get("/api/v2/auth/me", headers=h).status_code == 401                           # revoked
    r = client.post("/api/v2/auth/tokens", headers=H["olivia"], json={"name": "old"})
    with app.state.sessionmaker() as db:
        db.get(ApiToken, r.json()["token_id"]).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 401


ROLE_MATRIX = [
    # (method, path, json, roles that pass the role check)
    ("POST", "/api/v2/owners", {"public_key": "00" * 32, "label": "x"}, {"owner", "admin"}),
    ("POST", "/api/v2/registrations", {}, {"owner", "admin"}),
    ("POST", "/api/v2/claims/999/proofs", {"proof": {"a": 1}, "public": ["1"] * 5}, {"owner", "admin"}),
    ("POST", "/api/v2/deployments", {"name": "d", "environment": "e", "artifact_path": "/x"}, {"owner", "admin"}),
    ("POST", "/api/v2/embeddings", {"model_artifact_id": 999, "owner_id": 999, "config": {}}, {"owner", "admin"}),
    ("POST", "/api/v2/attacks/runs", {"step": "attacks"}, {"owner", "admin"}),
    ("POST", "/api/v2/jobs/nope/cancel", {}, {"owner", "admin"}),
    ("POST", "/api/v2/deployments/999/check", {}, {"owner", "admin"}),
    ("POST", "/api/v2/claims", {"registration_id": 999, "suspect_artifact_id": 999}, {"verifier", "admin"}),
    ("POST", "/api/v2/verifications", {"proof_id": 999}, {"verifier", "admin"}),
    ("GET", "/api/v2/audit/events", None, {"verifier", "admin"}),
    ("GET", "/api/v2/audit/verify", None, {"verifier", "admin"}),
    ("GET", "/api/v2/audit/export", None, {"verifier", "admin"}),
    ("GET", "/api/v2/users", None, {"admin"}),
    ("POST", "/api/v2/users", {"username": "zed", "password": "x", "role": "owner"}, {"admin"}),
]


@pytest.mark.parametrize("method,path,body,allowed", ROLE_MATRIX)
def test_role_matrix(env, method, path, body, allowed):
    """A verifier can't reach owner endpoints (and vice versa); only admins manage users."""
    app, client, H = env
    for user, role in (("olivia", "owner"), ("victor", "verifier"), ("ada", "admin")):
        r = client.request(method, path, headers=H[user], json=body)
        if role in allowed:
            assert r.status_code != 403, (user, path, r.text)
        else:
            assert r.status_code == 403 and "needs the role" in r.json()["detail"], (user, path, r.text)


def test_user_admin(env):
    app, client, H = env
    r = client.post("/api/v2/users", headers=H["ada"], json={"username": "vera", "password": "short", "role": "verifier"})
    assert r.status_code == 422
    r = client.post("/api/v2/users", headers=H["ada"], json={"username": "vera", "password": PASSWORD, "role": "verifier"})
    assert r.status_code == 201 and r.json()["role"] == "verifier"
    assert client.post("/api/v2/users", headers=H["ada"],
                       json={"username": "vera", "password": PASSWORD, "role": "owner"}).status_code == 409
    assert client.post("/api/v2/users", headers=H["ada"],
                       json={"username": "x y", "password": PASSWORD, "role": "owner"}).status_code == 422
    hv = bearer(client, "vera")
    assert client.patch(f"/api/v2/users/{r.json()['id']}", headers=H["ada"], json={"is_active": False}).status_code == 200
    assert client.get("/api/v2/auth/me", headers=hv).status_code == 401                 # deactivated
    me = client.get("/api/v2/auth/me", headers=H["ada"]).json()
    assert client.patch(f"/api/v2/users/{me['id']}", headers=H["ada"], json={"role": "owner"}).status_code == 422
    assert {u["username"] for u in client.get("/api/v2/users", headers=H["ada"]).json()} >= {"ada", "olivia", "vera"}


def test_create_admin_cli(tmp_path, monkeypatch, capsys):
    from backend.app import cli
    from backend.testing import database
    with database() as url:
        monkeypatch.setenv("SIGIL_VAR_DIR", str(tmp_path / "var"))
        if url:
            monkeypatch.setenv("DATABASE_URL", url)
        else:
            monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("SIGIL_ADMIN_PASSWORD", "a long admin password")
        assert cli.main(["create-admin", "--username", "root"]) == 0
        assert "created admin 'root'" in capsys.readouterr().out
        with pytest.raises(SystemExit):
            cli.main(["create-admin", "--username", "root"])                            # exists
        with app_client(tmp_path, database_url=url) as (app, client):
            r = client.post("/api/v2/auth/login", json={"username": "root", "password": "a long admin password"})
            assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
