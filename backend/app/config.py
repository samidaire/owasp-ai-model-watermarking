"""Settings, read from the environment (and backend/.env if present) with pydantic-settings.

Every variable is optional; the defaults give a local development setup:
  DATABASE_URL                 postgresql+psycopg://user:pass@127.0.0.1:5432/sigil  (default: SQLite file in backend/var)
  SIGIL_SIMULATE               1 = v1 runs replay recorded logs (contract/fixtures/logs), nothing executes
  SIGIL_UI_DIR                 static UI build to serve (default frontend/dist)
  SIGIL_REGISTRY_KEY           registry Ed25519 key file (default backend/var/registry.key, created on first run)
  SIGIL_REGISTRY_PASSPHRASE    passphrase that encrypts it (default: a random one kept in backend/var, dev only)
See docs/backend.md for the full list.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
DEMO = REPO / "demo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGIL_", env_file=str(BACKEND / ".env"), env_file_encoding="utf-8",
                                      extra="ignore", populate_by_name=True)

    # ------------------------------------------------------------------ storage
    database_url: str = Field(default="", validation_alias=AliasChoices("DATABASE_URL", "SIGIL_DATABASE_URL"),
                              description="SQLAlchemy URL; empty = SQLite file backend/var/sigil.db (development only)")
    var_dir: Path = Field(default=BACKEND / "var", description="runtime state: SQLite file, registry key, uploads")
    storage_dir: Path | None = Field(default=None, description="uploaded model files (default <var_dir>/uploads)")
    auto_migrate: bool = Field(default=True, description="run `alembic upgrade head` at start-up")
    auto_import_demo: bool = Field(default=True, description="import demo/results as history into an empty database")

    # ------------------------------------------------------------------ v1 demo (demo/server.py parity)
    simulate: bool = False
    ui_dir: Path = REPO / "frontend" / "dist"
    results_dir: Path = DEMO / "results"
    demo_python: str = Field(default="", description="interpreter for live demo runs (default: this Python)")
    sim_delay: float = 1.0
    probe_env: bool = True
    sse_keepalive: float = 10.0
    sse_poll: float = 0.05

    # ------------------------------------------------------------------ registry (CR-03)
    registry_key_path: Path | None = Field(default=None,
                                           validation_alias=AliasChoices("SIGIL_REGISTRY_KEY", "SIGIL_REGISTRY_KEY_PATH"))
    registry_passphrase: SecretStr | None = None
    trusted_registry_keys: str = Field(default="", description="extra trusted registry public keys (hex, comma-separated)")

    # ------------------------------------------------------------------ uploads, monitoring, auth
    max_upload_bytes: int = 500 * 1024 * 1024
    max_json_bytes: int = 1024 * 1024
    deployment_roots: str = Field(default="", description="folders deployments may point into (os.pathsep-separated); "
                                                          "default <var_dir>/deployments and the upload folder")
    monitor_interval: float = Field(default=3600.0, description="seconds between scheduled deployment re-checks; 0 = off")
    token_ttl_days: int = Field(default=90, description="lifetime of API tokens issued by /auth/login; 0 = no expiry")
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536

    # ------------------------------------------------------------------ misc
    log_level: str = "INFO"
    log_json: bool = True
    api_docs: bool = Field(default=False, description="serve Swagger UI at /api/docs (loads assets from a CDN)")

    # ------------------------------------------------------------------ derived values
    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.var_dir / 'sigil.db').resolve().as_posix()}"

    @property
    def uploads(self) -> Path:
        return Path(self.storage_dir or self.var_dir / "uploads")

    @property
    def registry_key(self) -> Path:
        return Path(self.registry_key_path or self.var_dir / "registry.key")

    @property
    def python_exe(self) -> str:
        return self.demo_python or sys.executable

    @property
    def deployment_root_paths(self) -> list[Path]:
        if self.deployment_roots.strip():
            return [Path(p).resolve() for p in self.deployment_roots.split(os.pathsep) if p.strip()]
        return [(self.var_dir / "deployments").resolve(), self.uploads.resolve()]

    @property
    def extra_registry_keys(self) -> set[str]:
        return {k.strip().lower() for k in self.trusted_registry_keys.split(",") if k.strip()}
