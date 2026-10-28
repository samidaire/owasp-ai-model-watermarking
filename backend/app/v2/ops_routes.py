"""Jobs, attack runs, deployments and demo history (API-03, API-04, API-09, DB-04)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..auth import actor, current_user, get_db, require
from ..jobs import db_job, status_of
from ..models import AttackRun, Deployment, DeploymentCheck, JobRow, ModelArtifact, ResultSnapshot, User
from ..monitor import check_deployment, resolve_artifact
from ..problems import ProblemError, responses
from . import schemas as S
from .common import Page, attack_run_out, check_out, deployment_out, get_or_404

router = APIRouter()


# ---------------------------------------------------------------------------------------------- jobs
def job_out(job=None, row: JobRow | None = None, output=None) -> dict:
    if job is not None:
        with job.cond:
            lines = list(job.lines)
        return {**job.info(), "status": status_of(job), "simulated": job.simulated, "tries": job.tries,
                "timeout": job.timeout, "source": getattr(job, "source", "v1"),
                "output": lines if output else None}
    return {"id": row.id, "step": row.step, "status": row.status, "code": row.code, "simulated": row.simulated,
            "tries": row.tries, "cancelled": row.cancelled, "timed_out": row.timed_out, "timeout": row.timeout,
            "started": row.started, "ended": row.ended, "lines": row.lines, "source": row.source,
            "output": output}


@router.get("/jobs", summary="Job history, newest first", response_model=list[S.JobOut], tags=["jobs"], responses=responses(401))
def list_jobs(request: Request, page: Page = Depends(), user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    request.app.state.jobs.store.flush(5)
    rows = db.scalars(select(JobRow).order_by(JobRow.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    mgr = request.app.state.jobs
    return [job_out(mgr.get(r.id)) if mgr.get(r.id) is not None else job_out(row=r) for r in rows]


@router.get("/jobs/{job_id}", summary="One job (add ?output=true for every line)", response_model=S.JobOut, tags=["jobs"], responses=responses(401, 404))
def get_job(job_id: str, request: Request, output: bool = Query(False, description="include every output line"),
            user: User = Depends(current_user)):
    job = request.app.state.jobs.get(job_id)
    if job is not None:
        return job_out(job, output=output)
    row, lines = db_job(request.app.state.sessionmaker, job_id)
    if row is None:
        raise ProblemError(404, f"job {job_id} not found")
    return job_out(row=row, output=lines if output else None)


@router.post("/jobs/{job_id}/cancel", response_model=S.JobOut, status_code=202, tags=["jobs"],
             responses=responses(401, 403, 404, 409), summary="Cancel a queued or running job")
def cancel_job(job_id: str, request: Request, user: User = Depends(require("owner")), db: Session = Depends(get_db)):
    job, stopped = request.app.state.jobs.cancel(job_id)
    if job is None:
        row, _ = db_job(request.app.state.sessionmaker, job_id)
        if row is None:
            raise ProblemError(404, f"job {job_id} not found")
        raise ProblemError(409, "job not running", job_status=row.status)
    if not stopped:
        raise ProblemError(409, "job not running", job_status=status_of(job))
    audit.append(db, actor(user), "job.cancelled", "job", job.id, {"step": job.step})
    return job_out(job)


# ---------------------------------------------------------------------------------------------- attacks
@router.get("/attacks/runs", summary="Attack runs, newest first", response_model=list[S.AttackRunOut], tags=["attacks"], responses=responses(401))
def list_attack_runs(page: Page = Depends(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(AttackRun).options(selectinload(AttackRun.results)).order_by(AttackRun.id.desc())
    return [attack_run_out(r) for r in db.scalars(q.limit(page.limit).offset(page.offset))]


@router.get("/attacks/runs/{run_id}", summary="One attack run with every attack's accuracy, BER and verdict", response_model=S.AttackRunOut, tags=["attacks"], responses=responses(401, 404))
def get_attack_run(run_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return attack_run_out(get_or_404(db, AttackRun, run_id, "attack run"), with_results=True)


@router.post("/attacks/runs", response_model=S.JobOut, status_code=202, tags=["attacks"],
             responses=responses(401, 403, 422),
             summary="Start the demo attack suite as a job (queued behind a running job; one GPU job at a time)")
def start_attack_run(request: Request, body: S.AttackJobCreate | None = None, user: User = Depends(require("owner")),
                     db: Session = Depends(get_db)):
    step = (body or S.AttackJobCreate()).step
    job = request.app.state.jobs.submit(step, queue_if_busy=True, user_id=user.id, source="v2")
    audit.append(db, actor(user), "attack.job_started", "job", job.id, {"step": step, "queued": job.queued})
    return job_out(job)


# ---------------------------------------------------------------------------------------------- deployments
@router.post("/deployments", response_model=S.DeploymentOut, status_code=201, tags=["deployments"],
             responses=responses(401, 403, 404, 422), summary="Register a deployment to monitor")
def create_deployment(body: S.DeploymentCreate, request: Request, user: User = Depends(require("owner")),
                      db: Session = Depends(get_db)):
    s = request.app.state.settings
    if resolve_artifact(s, body.artifact_path) is None:
        raise ProblemError(422, "artifact_path must be an absolute path inside one of the deployment roots "
                                "(SIGIL_DEPLOYMENT_ROOTS)")
    expected = body.expected_sha256
    if body.model_artifact_id is not None:
        art = get_or_404(db, ModelArtifact, body.model_artifact_id, "artifact")
        expected = expected or art.sha256
    if not expected:
        raise ProblemError(422, "give expected_sha256 or model_artifact_id")
    dep = Deployment(name=body.name, environment=body.environment, artifact_path=body.artifact_path,
                     expected_sha256=expected.lower(), model_artifact_id=body.model_artifact_id, active=True,
                     last_status="pending", created_by=user.id)
    db.add(dep)
    db.flush()
    audit.append(db, actor(user), "deployment.created", "deployment", dep.id,
                 {"name": dep.name, "environment": dep.environment, "expected_sha256": dep.expected_sha256})
    return deployment_out(dep)


@router.get("/deployments", summary="List monitored deployments", response_model=list[S.DeploymentOut], tags=["deployments"], responses=responses(401))
def list_deployments(page: Page = Depends(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Deployment).order_by(Deployment.id).limit(page.limit).offset(page.offset)
    return [deployment_out(d) for d in db.scalars(q)]


@router.get("/deployments/alerts", response_model=list[S.DeploymentOut], tags=["deployments"],
            responses=responses(401), summary="Active deployments whose last check raised an alert")
def deployment_alerts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Deployment).where(Deployment.active.is_(True), Deployment.last_status.in_(("mismatch", "missing", "error")))
    return [deployment_out(d) for d in db.scalars(q.order_by(Deployment.id))]


@router.get("/deployments/{deployment_id}", summary="One deployment and its last status", response_model=S.DeploymentOut, tags=["deployments"],
            responses=responses(401, 404))
def get_deployment(deployment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return deployment_out(get_or_404(db, Deployment, deployment_id, "deployment"))


@router.patch("/deployments/{deployment_id}", response_model=S.DeploymentOut, tags=["deployments"],
              responses=responses(401, 403, 404, 422), summary="Pause/resume monitoring or accept a new hash")
def update_deployment(deployment_id: int, body: S.DeploymentUpdate, user: User = Depends(require("owner")),
                      db: Session = Depends(get_db)):
    dep = get_or_404(db, Deployment, deployment_id, "deployment")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(dep, k, v.lower() if k == "expected_sha256" else v)
    audit.append(db, actor(user), "deployment.updated", "deployment", dep.id, changes)
    return deployment_out(dep)


@router.post("/deployments/{deployment_id}/check", response_model=S.DeploymentCheckOut, tags=["deployments"],
             responses=responses(401, 403, 404), summary="Re-hash the artefact now; a mismatch raises an alert")
def check_now(deployment_id: int, request: Request, user: User = Depends(require("owner")),
              db: Session = Depends(get_db)):
    dep = get_or_404(db, Deployment, deployment_id, "deployment")
    return check_out(check_deployment(db, request.app.state.settings, dep, "manual", actor(user)))


@router.get("/deployments/{deployment_id}/checks", summary="Check history of a deployment, newest first", response_model=list[S.DeploymentCheckOut], tags=["deployments"],
            responses=responses(401, 404))
def list_checks(deployment_id: int, page: Page = Depends(), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    get_or_404(db, Deployment, deployment_id, "deployment")
    q = select(DeploymentCheck).where(DeploymentCheck.deployment_id == deployment_id) \
        .order_by(DeploymentCheck.id.desc()).limit(page.limit).offset(page.offset)
    return [check_out(c) for c in db.scalars(q)]


# ---------------------------------------------------------------------------------------------- demo history
@router.get("/history/results", response_model=list[S.SnapshotOut], tags=["system"], responses=responses(401),
            summary="Versions of the demo result files (DB-04), newest first")
def list_snapshots(page: Page = Depends(), name: str | None = None, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    q = select(ResultSnapshot).order_by(ResultSnapshot.id.desc())
    if name:
        q = q.where(ResultSnapshot.name == name)
    return [{"id": r.id, "name": r.name, "path": r.path, "sha256": r.sha256, "commitment": r.commitment,
             "source": r.source, "imported_at": r.imported_at} for r in db.scalars(q.limit(page.limit).offset(page.offset))]


@router.get("/history/results/{snapshot_id}", summary="One result-file version, with content", response_model=S.SnapshotOut, tags=["system"],
            responses=responses(401, 404))
def get_snapshot(snapshot_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_or_404(db, ResultSnapshot, snapshot_id, "snapshot")
    return {"id": r.id, "name": r.name, "path": r.path, "sha256": r.sha256, "commitment": r.commitment,
            "source": r.source, "imported_at": r.imported_at, "content": r.content}
