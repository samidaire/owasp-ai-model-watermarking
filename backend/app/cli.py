"""Administration commands:  python -m backend.app.cli <command>

  migrate                     alembic upgrade head on DATABASE_URL
  create-admin --username U   create an admin account (password from SIGIL_ADMIN_PASSWORD or a prompt)
  create-user --username U --role owner|verifier|admin
  import-demo [--results DIR] import demo/results/*.json as history (DB-04; idempotent)
  verify-audit [--export F]   check the audit hash chain in the database, or in an exported JSON/CSV file
  export-openapi [--out F]    write the OpenAPI spec (default contract/openapi.json) (API-07)
  backup --out F              SQLite: online copy; PostgreSQL: pg_dump -Fc (needs pg_dump on PATH)
  restore --from F            SQLite: copy back (server stopped); PostgreSQL: pg_restore --clean
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from .config import REPO, Settings

OPENAPI_OUT = REPO / "contract" / "openapi.json"


def _session(settings: Settings, migrate: bool = True):
    from .db import make_engine, make_sessionmaker, run_migrations
    engine = make_engine(settings.db_url)
    if migrate:
        run_migrations(engine)
    return engine, make_sessionmaker(engine)


def openapi_document() -> dict:
    """The spec of an app built with default settings (nothing machine-specific ends up in it)."""
    from .main import create_app
    return create_app(Settings(_env_file=None)).openapi()


def openapi_text() -> str:
    return json.dumps(openapi_document(), indent=2, ensure_ascii=False) + "\n"


def _password(env: str, prompt: str) -> str:
    pw = os.environ.get(env)
    if pw:
        return pw
    pw = getpass.getpass(prompt)
    if pw != getpass.getpass("again: "):
        raise SystemExit("passwords differ")
    return pw


def cmd_migrate(a, s):
    from .db import make_engine, run_migrations
    run_migrations(make_engine(s.db_url))
    print("database is at the latest revision")


def _create(a, s, role):
    from . import audit
    from .auth import create_user
    from .problems import ProblemError
    engine, sm = _session(s)
    pw = _password("SIGIL_ADMIN_PASSWORD" if role == "admin" else "SIGIL_USER_PASSWORD", f"password for {a.username}: ")
    with sm() as db:
        try:
            u = create_user(db, s, a.username, pw, role)
        except ProblemError as e:
            raise SystemExit(f"error: {e.detail}") from e
        audit.append(db, "system:cli", "user.created", "user", u.id, {"username": u.username, "role": role})
    engine.dispose()
    print(f"created {role} {a.username!r} (id {u.id}); sign in with POST /api/v2/auth/login")


def cmd_create_admin(a, s):
    _create(a, s, "admin")


def cmd_create_user(a, s):
    _create(a, s, a.role)


def cmd_import_demo(a, s):
    from .history import import_demo
    engine, sm = _session(s)
    with sm() as db:
        counts = import_demo(db, Path(a.results or s.results_dir), actor="system:cli")
    engine.dispose()
    print(json.dumps(counts))


def cmd_verify_audit(a, s):
    from . import audit
    if a.export:
        text = Path(a.export).read_text(encoding="utf-8")
        if a.export.lower().endswith(".csv"):
            from .reports import verify_audit_csv
            result = verify_audit_csv(text)
        else:
            doc = json.loads(text)
            result = audit.verify_events(doc["events"])
            from .registry import verify_document
            result["signature_problems"] = verify_document(doc, {doc.get("registry_public_key", "")})
    else:
        engine, sm = _session(s, migrate=False)
        with sm() as db:
            result = audit.verify_chain(db)
        engine.dispose()
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] and not result.get("signature_problems") else 1


def cmd_export_openapi(a, s):
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(openapi_text(), encoding="utf-8", newline="\n")
    print(f"wrote {out}")


def _pg_args(url: str) -> tuple[list[str], dict]:
    from sqlalchemy.engine import make_url
    u = make_url(url)
    env = dict(os.environ)
    if u.password:
        env["PGPASSWORD"] = u.password            # never on the command line
    args = ["-h", u.host or "127.0.0.1", "-p", str(u.port or 5432), "-U", u.username or "postgres", "-d", u.database]
    return args, env


def cmd_backup(a, s):
    url = s.db_url
    out = Path(a.out)
    if url.startswith("sqlite"):
        src = sqlite3.connect(url.split("///", 1)[1])
        dst = sqlite3.connect(out)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    else:
        if not shutil.which("pg_dump"):
            raise SystemExit("pg_dump not found: install the PostgreSQL client tools, or run "
                             "`docker compose exec db pg_dump -U sigil -Fc sigil > backup.dump`")
        args, env = _pg_args(url)
        subprocess.run(["pg_dump", "-Fc", "-f", str(out), *args], check=True, env=env)
    print(f"backup written to {out}")


def cmd_restore(a, s):
    url = s.db_url
    src = Path(getattr(a, "from"))
    if url.startswith("sqlite"):
        shutil.copyfile(src, url.split("///", 1)[1])
    else:
        if not shutil.which("pg_restore"):
            raise SystemExit("pg_restore not found: install the PostgreSQL client tools")
        args, env = _pg_args(url)
        subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", *args, str(src)], check=True, env=env)
    print(f"restored from {src}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m backend.app.cli", description="Sigil backend administration")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="alembic upgrade head").set_defaults(fn=cmd_migrate)
    p = sub.add_parser("create-admin", help="create an admin account")
    p.add_argument("--username", required=True)
    p.set_defaults(fn=cmd_create_admin)
    p = sub.add_parser("create-user", help="create an owner, verifier or admin account")
    p.add_argument("--username", required=True)
    p.add_argument("--role", required=True, choices=["owner", "verifier", "admin"])
    p.set_defaults(fn=cmd_create_user)
    p = sub.add_parser("import-demo", help="import demo/results/*.json as history")
    p.add_argument("--results", help="results folder (default: demo/results)")
    p.set_defaults(fn=cmd_import_demo)
    p = sub.add_parser("verify-audit", help="verify the audit hash chain")
    p.add_argument("--export", help="verify an exported audit JSON/CSV file instead of the database")
    p.set_defaults(fn=cmd_verify_audit)
    p = sub.add_parser("export-openapi", help="write the OpenAPI spec")
    p.add_argument("--out", default=str(OPENAPI_OUT))
    p.set_defaults(fn=cmd_export_openapi)
    p = sub.add_parser("backup", help="back up the database")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("restore", help="restore the database from a backup (stop the server first)")
    p.add_argument("--from", required=True)
    p.set_defaults(fn=cmd_restore)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    rc = a.fn(a, Settings())
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
