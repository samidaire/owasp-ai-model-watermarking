"""Demo history (DB-04): demo/results/*.json as versioned snapshots, plus attack runs.

`python -m backend.app.cli import-demo` (and the first start on an empty database) imports every result file
the panels read; after each successful live run the job's results are snapshotted again. Snapshots are keyed
by (name, SHA-256), so importing twice is a no-op and each distinct version of a file is kept once.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit
from .models import AttackResult, AttackRun, ResultSnapshot

RESULT_FILES = {
    "public_commitment": "public_commitment.json",
    "train": "train.json",
    "attacks": "attacks.json",
    "forgery": "forgery.json",
    "committed_seed": "committed_seed.json",
    "vk_crosscheck": "vk_crosscheck.json",
    **{f"ezkl_{v}_{w}": f"ezkl_{v}_{w}/summary.json" for v in ("private", "hashed") for w in ("owner", "thief")},
    "protocol_v2": "protocol_v2.json",
}
# files each v1 step rewrites (UI_INTEGRATION.md §4.2)
STEP_FILES = {"evaluate": ["train"], "retrain": ["public_commitment", "train"], "attacks": ["attacks"],
              "forgery": ["forgery"], "committed": ["committed_seed"],
              "zk": ["ezkl_private_owner", "ezkl_private_thief", "vk_crosscheck"],
              "zk_hashed": ["ezkl_hashed_owner", "ezkl_hashed_thief"], "protocol_v2": ["protocol_v2"],
              "all": ["train", "attacks", "forgery", "committed_seed", "ezkl_private_owner", "ezkl_private_thief",
                      "vk_crosscheck"]}


def _read(path: Path):
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except (OSError, ValueError):
        return None, None


def snapshot(db: Session, results_dir: Path, names, source: str) -> dict:
    """Store the current version of each named result file (if new). Returns {"snapshots": n, "attack_runs": n}."""
    added, runs = 0, 0
    for name in names:
        rel = RESULT_FILES[name]
        raw, content = _read(Path(results_dir) / rel)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if db.scalar(select(ResultSnapshot.id).where(ResultSnapshot.name == name, ResultSnapshot.sha256 == sha)):
            continue
        commitment = (content.get("commitment") or content.get("commitment_sha256")) if isinstance(content, dict) else None
        db.add(ResultSnapshot(name=name, path=rel, sha256=sha, commitment=commitment if isinstance(commitment, str) else None,
                              content=content, source=source))
        added += 1
        if name == "attacks" and isinstance(content, dict):
            runs += record_attack_run(db, content, sha, source=source.split(":")[0], job_id=None, simulated=False)
    db.flush()
    return {"snapshots": added, "attack_runs": runs}


def record_attack_run(db: Session, content: dict, sha: str, *, source: str, job_id: str | None,
                      simulated: bool, force: bool = False) -> int:
    """One attack_runs row (+ results) for an attacks.json. Skipped when this exact file is already recorded,
    unless `force` (a job re-ran the suite, even if the numbers came out identical)."""
    if not force and db.scalar(select(AttackRun.id).where(AttackRun.results_sha256 == sha)):
        return 0
    run = AttackRun(job_id=job_id, source=source, commitment=content.get("commitment"),
                    threshold=content.get("threshold"), simulated=simulated, results_sha256=sha)
    for r in content.get("rows", []) or []:
        if isinstance(r, dict):
            run.results.append(AttackResult(attack=str(r.get("attack", ""))[:200], family=str(r.get("family", ""))[:40],
                                            accuracy=r.get("accuracy"), owner_ber=r.get("owner_ber"),
                                            survives=r.get("survives")))
    db.add(run)
    return 1


def import_demo(db: Session, results_dir: Path, actor: str = "system:import-demo") -> dict:
    counts = snapshot(db, results_dir, list(RESULT_FILES), source="demo-import")
    audit.append(db, actor, "demo.import", "result_snapshots", None, counts)
    return counts


def is_empty(db: Session) -> bool:
    return not db.scalar(select(func.count()).select_from(ResultSnapshot))


def after_job(session_factory, settings, job) -> None:
    """Finish hook of every job: snapshot what a successful live run wrote, record attack runs, audit."""
    job.manager.store.flush()          # the jobs row must exist before attack_runs can reference it
    with session_factory() as db:
        details = {"step": job.step, "code": job.code, "cancelled": job.cancelled, "timed_out": job.timed_out,
                   "simulated": job.simulated}
        if job.code == 0:
            if not job.simulated:
                details.update(snapshot(db, settings.results_dir, STEP_FILES.get(job.step, []), source=f"job:{job.id}"))
            if job.step in ("attacks", "all"):
                raw, content = _read(Path(settings.results_dir) / "attacks.json")
                if isinstance(content, dict):
                    record_attack_run(db, content, hashlib.sha256(raw).hexdigest(), source="job", job_id=job.id,
                                      simulated=job.simulated, force=True)
        audit.append(db, "system:job-runner", "job.finished", "job", job.id, details)
