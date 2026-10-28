"""API-01: the security middleware rules, static UI serving with SPA fallback, error formats (API-10)."""
import json

import pytest

pytest.importorskip("fastapi")

from backend.testing import app_client  # noqa: E402

PROBLEM = "application/problem+json"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mw")
    ui = tmp / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (ui / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    with app_client(tmp, ui_dir=ui, max_json_bytes=2048) as (app, client):
        yield app, client


# ---------------------------------------------------------------------------------------------- static UI
def test_ui_index_assets_and_spa_fallback(env):
    _, c = env
    r = c.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache" and "<title>t</title>" in r.text
    r = c.get("/assets/app.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "max-age=3600"
    r = c.get("/panels/b/deep/link")                                  # client-side route
    assert r.status_code == 200 and "<title>t</title>" in r.text
    assert c.get("/../../README.md").status_code in (200, 404)        # never escapes the UI folder
    assert "Requirements" not in c.get("/..%2f..%2fREADME.md").text


def test_no_ui_build_is_503(tmp_path):
    with app_client(tmp_path, ui_dir=tmp_path / "missing") as (_, c):
        r = c.get("/")
        assert r.status_code == 503 and "no UI build" in r.json()["error"]
        assert c.get("/api/state").status_code == 200


def test_upload_folder_must_be_outside_the_static_root(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    with pytest.raises(RuntimeError, match="outside the static"):
        with app_client(tmp_path, ui_dir=ui, storage_dir=ui / "uploads"):
            pass


def test_security_headers_everywhere(env):
    _, c = env
    for path in ("/", "/api/state", "/api/v2/health", "/results/train.json"):
        h = c.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY", path
        assert h["referrer-policy"] == "no-referrer"


# ---------------------------------------------------------------------------------------------- host / origin / type
def test_v2_errors_are_problem_json(env):
    _, c = env
    r = c.get("/api/v2/owners")
    assert r.status_code == 401 and r.headers["content-type"] == PROBLEM
    body = r.json()
    assert body["status"] == 401 and body["title"] and body["instance"] == "/api/v2/owners"
    assert r.headers["www-authenticate"] == "Bearer"
    r = c.get("/api/v2/no-such-thing")
    assert r.status_code == 404 and r.headers["content-type"] == PROBLEM
    r = c.post("/api/v2/auth/login", json={"username": "x"})            # validation error
    assert r.status_code == 422 and r.headers["content-type"] == PROBLEM and r.json()["errors"]


def test_host_check_applies_to_v2_and_ui(env):
    _, c = env
    for path in ("/api/v2/health", "/", "/results/train.json"):
        r = c.get(path, headers={"host": "attacker.example"})
        assert r.status_code == 403, path
    r = c.get("/api/v2/health", headers={"host": "attacker.example"})
    assert r.headers["content-type"] == PROBLEM


def test_origin_check_on_every_state_changing_method(env):
    _, c = env
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        r = c.request(method, "/api/v2/auth/login", content=b"{}",
                      headers={"content-type": "application/json", "origin": "https://evil.example"})
        assert r.status_code == 403 and r.headers["content-type"] == PROBLEM, method
    r = c.post("/api/v2/auth/login", json={"username": "a", "password": "b"}, headers={"origin": "http://localhost:5173"})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_json_content_type_required(env):
    _, c = env
    r = c.post("/api/v2/auth/login", content=b'{"username":"a","password":"b"}', headers={"content-type": "text/plain"})
    assert r.status_code == 415 and r.headers["content-type"] == PROBLEM
    r = c.post("/api/v2/auth/login", data={"username": "a", "password": "b"})        # an HTML form post
    assert r.status_code == 415
    r = c.post("/api/v2/owners", files={"file": ("x.onnx", b"\x08\x07")})             # multipart: uploads only
    assert r.status_code == 415
    r = c.post("/api/v2/models", files={"file": ("x.onnx", b"\x08\x07")})             # allowed, then 401
    assert r.status_code == 401
    r = c.delete("/api/v2/auth/tokens/1")                                             # no body: no type needed
    assert r.status_code == 401
    r = c.request("DELETE", "/api/v2/auth/tokens/1", content=b"x=1", headers={"content-type": "text/plain"})
    assert r.status_code == 415


def test_body_limits(env):
    _, c = env
    big = json.dumps({"username": "a", "password": "b" * 4000})
    r = c.post("/api/v2/auth/login", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.headers["content-type"] == PROBLEM

    def chunks():                                                     # no Content-Length: counted while reading
        yield b'{"username": "a", "password": "'
        for _ in range(10):
            yield b"x" * 1000
        yield b'"}'
    r = c.post("/api/v2/auth/login", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    r = c.post("/api/run", content=b"{}", headers={"content-type": "application/json", "content-length": "-5"})
    assert r.status_code in (400, 413)


def test_cors_preflight_for_v2(env):
    _, c = env
    r = c.options("/api/v2/owners", headers={"origin": "http://[::1]:5173", "access-control-request-method": "POST",
                                              "access-control-request-headers": "authorization,content-type"})
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == "http://[::1]:5173"
    assert "Authorization" in r.headers["access-control-allow-headers"]
    assert "DELETE" in r.headers["access-control-allow-methods"]
    assert c.options("/api/v2/owners", headers={"origin": "http://evil.example"}).status_code == 403


def test_v1_endpoints_need_no_token_but_v2_do(env):
    _, c = env
    assert c.get("/api/state").status_code == 200
    assert c.get("/api/steps").status_code == 200
    assert c.get("/api/v2/health").status_code == 200                  # public liveness probe
    assert c.get("/api/v2/registry").status_code == 200                # the registry public key is public
    for path in ("/api/v2/models", "/api/v2/audit/events", "/api/v2/environment", "/api/v2/jobs"):
        assert c.get(path).status_code == 401, path


def test_openapi_is_served_and_docs_off_by_default(env):
    _, c = env
    spec = c.get("/api/openapi.json").json()
    assert spec["info"]["title"] == "Sigil backend API"
    assert c.get("/api/docs").status_code == 404
