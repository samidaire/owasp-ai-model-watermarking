"""Test support for tests/test_backend_*.py (not used by the running app).

Database selection:
  * default: a fresh SQLite file per app;
  * SIGIL_TEST_DB=pg: a fresh database per app on an embedded PostgreSQL 16 (the `pgserver` wheel, data dir
    backend/var/test-pg, reused between runs), migrated with Alembic like production;
  * tests marked `pg` (tests/test_backend_pg.py) always use PostgreSQL and skip when pgserver is missing.
"""
from __future__ import annotations

import contextlib
import http.client
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path

from .app.config import BACKEND, Settings

_PG = {"server": None, "lock": threading.Lock()}
PG_DIR = BACKEND / "var" / "test-pg"


def pg_available() -> bool:
    try:
        import pgserver  # noqa: F401
        import psycopg  # noqa: F401
        return True
    except ImportError:
        return False


def _pg_server():
    with _PG["lock"]:
        if _PG["server"] is None:
            import pgserver
            PG_DIR.parent.mkdir(parents=True, exist_ok=True)
            _PG["server"] = pgserver.get_server(str(PG_DIR), cleanup_mode="stop")
        return _PG["server"]


def pg_database() -> tuple[str, callable]:
    """A fresh, empty PostgreSQL database: (SQLAlchemy URL, drop function)."""
    import psycopg
    srv = _pg_server()
    base = srv.get_uri()                                  # postgresql://postgres:@127.0.0.1:PORT/postgres
    name = "sigil_t_" + uuid.uuid4().hex[:12]
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = base.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://", 1) + "/" + name

    def drop():
        with contextlib.suppress(Exception), psycopg.connect(base, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    return url, drop


def use_pg() -> bool:
    return os.environ.get("SIGIL_TEST_DB", "").lower() in ("pg", "postgres", "postgresql")


def make_settings(tmp: Path, database_url: str = "", **over) -> Settings:
    """Settings for a test app: everything under `tmp`, fast password hashing, no probe, no scheduler."""
    base = dict(var_dir=tmp / "var", database_url=database_url, simulate=True, probe_env=False, monitor_interval=0,
                auto_import_demo=False, registry_passphrase="test registry passphrase", argon2_time_cost=1,
                argon2_memory_kib=1024, log_json=True, deployment_roots=str(tmp / "deploy"))
    base.update(over)
    return Settings(_env_file=None, **base)


@contextlib.contextmanager
def database(force_pg: bool = False):
    """Yields a database URL ('' = SQLite in the var folder)."""
    if force_pg or use_pg():
        url, drop = pg_database()
        try:
            yield url
        finally:
            drop()
    else:
        yield ""


@contextlib.contextmanager
def app_client(tmp: Path, force_pg: bool = False, **over):
    """(app, TestClient) on http://127.0.0.1 with the lifespan running."""
    from fastapi.testclient import TestClient

    from .app.main import create_app
    given = over.pop("database_url", None)
    with (contextlib.nullcontext(given) if given is not None else database(force_pg)) as url:
        app = create_app(make_settings(tmp, url, **over))
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            yield app, client


class LiveServer:
    """The app under a real uvicorn on an ephemeral 127.0.0.1 port (SSE, raw HTTP, process kills)."""

    def __init__(self, app):
        self.app = app

    def __enter__(self):
        import uvicorn
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        config = uvicorn.Config(self.app, log_config=None, timeout_graceful_shutdown=3, lifespan="on")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, daemon=True)
        self.thread.start()
        end = time.time() + 60
        while not self.server.started:
            if not self.thread.is_alive() or time.time() > end:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(20)


class Headers(dict):
    """Response headers with case-insensitive lookup (HTTP header names are case-insensitive)."""

    def __init__(self, pairs):
        super().__init__((k.lower(), v) for k, v in pairs)

    def __getitem__(self, k):
        return super().__getitem__(k.lower())

    def __contains__(self, k):
        return super().__contains__(k.lower())

    def get(self, k, default=None):
        return super().get(k.lower(), default)


def call(port, method, path, body=None, headers=None, host=None, timeout=20):
    """Raw HTTP call (no URL normalisation, explicit Host): (status, headers, parsed body). As tests/test_server.py."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    h = {"Host": f"127.0.0.1:{port}" if host is None else host}
    if isinstance(body, (dict, list)):
        body = json.dumps(body)
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    try:
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        try:
            parsed = json.loads(data)
        except ValueError:
            parsed = data
        return r.status, Headers(r.getheaders()), parsed
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------- accounts
PASSWORD = "correct horse battery"


def add_user(app, username: str, role: str, password: str = PASSWORD) -> int:
    from .app import audit
    from .app.auth import create_user
    with app.state.sessionmaker() as db:
        u = create_user(db, app.state.settings, username, password, role)
        audit.append(db, "test", "user.created", "user", u.id, {"username": username, "role": role})
        return u.id


def bearer(client, username: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/v2/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def wait_until(pred, timeout=10.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError("condition not met in time")


# ---------------------------------------------------------------------------------------------- synthetic world
def embed_like(seed, pkh, cfg, flips=0, scale=0.02):
    """A float32 vector whose quantised projections match the signature except for `flips` bits
    (as sdk/tests/test_protocol.py, but float32-exact so it survives a round trip through a model file)."""
    import numpy as np
    from sigil import protocol as P
    X = P.key_matrix(seed, pkh, cfg).astype(float)
    target = P.signature_bits(seed, pkh, cfg).astype(float) * 2 - 1
    target[:flips] *= -1
    w = X.T @ target / cfg.M * scale
    for _ in range(400):
        w32 = w.astype(np.float32).astype(np.float64)
        bad = np.sign(X @ P.quantize(w32, cfg)) != target
        if not bad.any():
            return w32
        w += 0.5 * scale * (X[bad].T @ target[bad]) / cfg.M
    raise AssertionError("could not construct the vector")


def onnx_model_bytes(w, layer: str = "conv2", out_channels: int = 4) -> bytes:
    """A one-Conv ONNX model whose `layer` kernel has Uchida vector exactly `w` (every output unit = w)."""
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    k = np.tile(np.asarray(w, dtype=np.float32).reshape(1, -1, 3, 3), (out_channels, 1, 1, 1))
    cin = k.shape[1]
    node = helper.make_node("Conv", ["x", f"{layer}.weight"], ["y"], name=layer, pads=[1, 1, 1, 1])
    graph = helper.make_graph([node], "g", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, cin, 8, 8])],
                              [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, out_channels, 8, 8])],
                              [numpy_helper.from_array(k, f"{layer}.weight")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], producer_name="sigil-tests")
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


def world(flips: int = 0):
    """An owner (key, seed), the demo config, a watermarked ONNX model and its signed registration."""
    import hashlib

    from sigil import protocol as P
    from sigil.identity import KeyPair
    from sigil.records import make_registration
    cfg = P.Config()
    owner = KeyPair.generate()
    seed = P.new_seed()
    pkh = P.pk_hash(owner.public_bytes)
    w = embed_like(seed, pkh, cfg, flips=flips)
    model = onnx_model_bytes(w)
    sha = hashlib.sha256(model).hexdigest()
    rec = make_registration(owner, seed, cfg, sha)
    return {"cfg": cfg, "owner": owner, "seed": seed, "pkh": pkh, "w": w, "model": model, "sha": sha, "rec": rec}
