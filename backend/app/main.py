"""Sigil backend (M6): FastAPI app factory.

    uvicorn backend.app.main:app --host 127.0.0.1 --port 8765          # or: python -m backend.app --simulate

Serves the UI build, the v1 demo API (demo/server.py parity, API-02) and the authenticated v2 API under
/api/v2 (API-03), behind the localhost-only security middleware (API-01). See docs/backend.md.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from . import __version__, history, problems, static, v1
from .config import Settings
from .db import make_engine, make_sessionmaker, run_migrations
from .jobs import JobManager, JobStore, recover_interrupted
from .logs import configure as configure_logging
from .logs import log
from .monitor import Monitor
from .registry import Registry
from .security import SecurityMiddleware
from .v2 import api_router

DESCRIPTION = """
**Sigil** backend: model registration with registry timestamps, ownership verification history,
deployment monitoring, a hash-chained audit log and reports.

* `/api/*` (v1): the unauthenticated localhost demo API of `demo/server.py` (UI_INTEGRATION.md §4).
* `/api/v2/*` (v2): authenticated with `Authorization: Bearer sgl_...` (from `POST /api/v2/auth/login`);
  errors are RFC 9457 `application/problem+json`.

Every state-changing request must be `Content-Type: application/json` (the two upload endpoints also take
`multipart/form-data`), come from a localhost `Host`, and carry no foreign `Origin`.
"""

TAGS = [
    {"name": "auth", "description": "Accounts, roles and API tokens (API-06)"},
    {"name": "owners", "description": "Owner identities: Ed25519 public keys only"},
    {"name": "models", "description": "Model uploads: size, extension and magic-byte checks, SHA-256 (API-05)"},
    {"name": "registry", "description": "Registrations and registry receipts (CR-02, CR-03)"},
    {"name": "claims and proofs", "description": "Verifier claims (fresh nonce) and owner proof bundles"},
    {"name": "verifications", "description": "Ownership verification with named reasons (ZK-06)"},
    {"name": "attacks", "description": "Robustness attack runs and results"},
    {"name": "jobs", "description": "Persisted demo jobs (API-04)"},
    {"name": "deployments", "description": "Deployment monitoring and alerts (API-09)"},
    {"name": "audit", "description": "Append-only hash-chained audit log (DB-03)"},
    {"name": "reports", "description": "Certificates, audit exports and the compliance report (API-08)"},
    {"name": "system", "description": "Health, environment and demo history"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    s: Settings = app.state.settings
    configure_logging(s.log_level, s.log_json)
    Path(s.var_dir).mkdir(parents=True, exist_ok=True)
    s.uploads.mkdir(parents=True, exist_ok=True)
    for root in (Path(s.ui_dir).resolve(), Path(s.results_dir).resolve()):
        if root == s.uploads.resolve() or root in s.uploads.resolve().parents:
            raise RuntimeError("the upload folder must be outside the static UI and results folders (API-05)")

    engine = make_engine(s.db_url)
    app.state.engine = engine
    app.state.sessionmaker = sm = make_sessionmaker(engine)
    if s.auto_migrate:
        await asyncio.to_thread(run_migrations, engine)
    app.state.registry = await asyncio.to_thread(Registry.load_or_create, s)

    interrupted = await asyncio.to_thread(recover_interrupted, sm)
    if interrupted:
        log.warning("marked %d interrupted job(s) as finished", len(interrupted), extra={"event": "jobs.recovered"})
    store = JobStore(sm)
    app.state.jobs = JobManager(s, store, on_finished=lambda job: history.after_job(sm, s, job))

    if s.auto_import_demo:
        def _import():
            with sm() as db:
                if history.is_empty(db):
                    history.import_demo(db, Path(s.results_dir))
        try:
            await asyncio.to_thread(_import)
        except Exception:  # noqa: BLE001 - history is optional; the demo must still start
            log.exception("could not import the demo history")

    app.state.env = {"status": "probing"}
    if s.probe_env:
        v1.start_probe(app)
    else:
        app.state.env = {"status": "error", "error": "environment probe disabled (SIGIL_PROBE_ENV=0)"}

    app.state.monitor = Monitor(app)
    app.state.monitor.start()

    log.info("backend started", extra={"event": "startup"})
    try:
        yield
    finally:
        await app.state.monitor.stop()
        await asyncio.to_thread(app.state.jobs.shutdown)
        await asyncio.to_thread(store.close)
        engine.dispose()
        log.info("backend stopped", extra={"event": "shutdown"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Sigil backend API", version=__version__, description=DESCRIPTION, lifespan=lifespan,
                  openapi_url="/api/openapi.json", openapi_tags=TAGS,
                  docs_url="/api/docs" if settings.api_docs else None, redoc_url=None)
    app.state.settings = settings
    problems.install(app)
    app.include_router(v1.router)
    app.include_router(api_router, prefix="/api/v2")
    app.include_router(static.router)          # last: the UI route catches every other GET
    app.add_middleware(SecurityMiddleware, settings=settings)
    return app


app = create_app()
