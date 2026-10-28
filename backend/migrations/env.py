"""Alembic environment. Used three ways:
  * programmatically by the app / CLI, which pass an open connection in config.attributes["connection"];
  * `alembic -c backend/alembic.ini upgrade head`, which uses DATABASE_URL (or sqlalchemy.url in the ini);
  * offline (`--sql`), which prints the DDL.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.app.config import Settings  # noqa: E402
from backend.app.models import Base  # noqa: E402

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or Settings().db_url


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:              # called by the app: don't touch its logging configuration
        _run(connection)
        return
    if config.config_file_name:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        _run(conn)
        conn.commit()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
