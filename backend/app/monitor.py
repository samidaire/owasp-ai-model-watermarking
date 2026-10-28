"""Deployment monitoring (API-09).

A deployment names an artefact on disk and the SHA-256 it must have. A check re-hashes the file and records a
deployment_checks row: ok, mismatch (alert: the deployed model was changed), missing (alert) or error (alert).
It also notes whether the observed hash has a registration in the registry. Checks run on demand
(POST /api/v2/deployments/{id}/check) and from a background asyncio task every SIGIL_MONITOR_INTERVAL seconds.

Watermark detection needs the owner's seed, which never reaches the server, so it is not part of the
scheduled check; owners run `sigil detect` on the artefact instead.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .logs import log
from .models import Deployment, DeploymentCheck, Registration


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_artifact(settings, raw: str) -> Path | None:
    """The artefact path, if it lies inside one of the allowed deployment roots (no reading arbitrary files)."""
    try:
        p = Path(raw).expanduser()
        p = p.resolve() if p.is_absolute() else None
    except (OSError, ValueError):
        return None
    if p is None:
        return None
    for root in settings.deployment_root_paths:
        if p == root or root in p.parents:
            return p
    return None


def check_deployment(db: Session, settings, dep: Deployment, trigger: str, actor: str) -> DeploymentCheck:
    observed, detail, registered = None, None, None
    path = resolve_artifact(settings, dep.artifact_path)
    if path is None:
        status, detail = "error", "the artefact path is outside the allowed deployment roots"
    elif not path.is_file():
        status, detail = "missing", "the artefact file does not exist"
    else:
        try:
            observed = sha256_file(path)
            status = "ok" if observed == dep.expected_sha256 else "mismatch"
            if status == "mismatch":
                detail = "the deployed artefact's SHA-256 differs from the expected hash"
            registered = db.scalar(select(Registration.id).where(Registration.model_sha256 == observed).limit(1)) is not None
        except OSError as e:
            status, detail = "error", f"could not read the artefact ({e.__class__.__name__})"
    previous = dep.last_status
    check = DeploymentCheck(deployment_id=dep.id, trigger=trigger, status=status, alert=status != "ok",
                            expected_sha256=dep.expected_sha256, observed_sha256=observed, registered=registered,
                            detail=detail)
    db.add(check)
    dep.last_status, dep.last_checked_at = status, datetime.now(timezone.utc)
    db.flush()
    details = {"status": status, "previous": previous, "trigger": trigger, "check_id": check.id,
               "observed_sha256": observed}
    if trigger == "manual" or status != previous:
        audit.append(db, actor, "deployment.alert" if check.alert else "deployment.check", "deployment", dep.id,
                     details)
    else:
        db.commit()
    if check.alert:
        log.warning("deployment %s: %s", dep.id, status, extra={"event": "deployment.alert"})
    return check


def check_all(session_factory, settings) -> int:
    n = 0
    with session_factory() as db:
        ids = db.scalars(select(Deployment.id).where(Deployment.active.is_(True))).all()
    for dep_id in ids:
        with session_factory() as db:
            dep = db.get(Deployment, dep_id)
            if dep is not None and dep.active:
                check_deployment(db, settings, dep, "scheduler", "system:monitor")
                n += 1
    return n


class Monitor:
    """The background re-check task (asyncio); interval SIGIL_MONITOR_INTERVAL seconds, 0 = off."""

    def __init__(self, app):
        self.app = app
        self.task: asyncio.Task | None = None
        self.runs = 0

    def start(self):
        if self.app.state.settings.monitor_interval > 0:
            self.task = asyncio.get_running_loop().create_task(self._loop(), name="deployment-monitor")

    async def _loop(self):
        s = self.app.state.settings
        while True:
            await asyncio.sleep(s.monitor_interval)
            try:
                await asyncio.to_thread(check_all, self.app.state.sessionmaker, s)
                self.runs += 1
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep monitoring
                log.exception("scheduled deployment check failed")

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
