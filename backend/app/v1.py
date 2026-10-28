"""v1 compatibility (API-02): the demo API of demo/server.py, unchanged, until the Phase 3 cutover.

Same paths, bodies, status codes, error messages and SSE framing as UI_INTEGRATION.md §4 (contract/types.ts).
These endpoints stay unauthenticated: they are the localhost demo, protected by the Host/Origin/JSON checks
of the security middleware. Differences, all additive: jobs and their output are persisted, so
GET /api/jobs/{id} and its stream still answer after a restart; every run/cancel writes an audit event.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import audit, legacy
from .jobs import Busy, db_job, row_info
from .logs import log
from .problems import v1_error, v1_json

router = APIRouter(tags=["v1 demo (unauthenticated, localhost)"])
ACTOR = "local:v1-demo"


# ---------------------------------------------------------------------------------------------- docs models
class JobInfo(BaseModel):
    id: str
    step: str
    running: bool
    code: int | None = Field(description="null while running; 0 ok; -2 cancelled; -3 timed out; other = failed")
    started: float
    ended: float | None
    lines: int
    cancelled: bool
    timed_out: bool


class JobDetail(JobInfo):
    output: list[str]


class RunRequest(BaseModel):
    step: str = Field(description="evaluate | retrain | attacks | forgery | committed | zk | zk_hashed | all")
    tries: int | None = Field(default=None, description="committed only: 20000 or 100000")


class ErrorBody(BaseModel):
    error: str
    job: JobInfo | None = None


V1_ERRORS = {c: {"model": ErrorBody} for c in (400, 403, 404, 409, 413, 415)}


# ---------------------------------------------------------------------------------------------- environment probe
def probe_env(settings) -> dict:
    """GPU/torch facts for the header badge, probed in a child process (demo/server.py's probe_env)."""
    code = ("import json,sys,torch;d={'python':sys.version.split()[0],'torch':torch.__version__,"
            "'cuda':torch.version.cuda,'gpu':None}\n"
            "if torch.cuda.is_available():\n p=torch.cuda.get_device_properties(0);"
            "d['gpu']=p.name;d['sm']=f'sm_{p.major}{p.minor}';d['vram_gib']=round(p.total_memory/2**30,1)\n"
            "print(json.dumps(d))")
    try:
        out = subprocess.run([settings.python_exe, "-c", code], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120, env=legacy.child_env())
        lines = (out.stdout or "").strip().splitlines()
        if out.returncode == 0 and lines:
            return {**json.loads(lines[-1]), "status": "ok"}
        err = (out.stderr or "").strip().splitlines()
        detail = err[-1].strip() if err else f"probe exited with code {out.returncode} and no output"
    except Exception as e:  # noqa: BLE001 - surfaced in the UI, never fatal
        detail = f"{e.__class__.__name__}: {e}"
    return {"status": "error",
            "error": legacy.scrub_paths(f"torch not available to {legacy.rel(settings.python_exe)}: {detail}")}


def start_probe(app) -> None:
    def run():
        app.state.env = probe_env(app.state.settings)
    import threading
    threading.Thread(target=run, daemon=True, name="env-probe").start()


# ---------------------------------------------------------------------------------------------- state
def demo_state(app) -> dict:
    s = app.state.settings
    results = Path(s.results_dir)
    job = app.state.jobs.current
    return {
        "api_version": legacy.API_VERSION,
        "mode": "simulate" if s.simulate else "live",
        "env": app.state.env,
        "commitment": legacy.current_commitment(results),
        "results": {
            "train": legacy.read_json(results / "train.json"),
            "attacks": legacy.read_json(results / "attacks.json"),
            "forgery": legacy.read_json(results / "forgery.json"),
            "committed_seed": legacy.read_json(results / "committed_seed.json"),
            "vk_crosscheck": legacy.read_json(results / "vk_crosscheck.json"),
            "ezkl": {f"{v}_{w}": legacy.read_json(results / f"ezkl_{v}_{w}" / "summary.json")
                     for v in ("private", "hashed") for w in ("owner", "thief")},
            "protocol_v2": legacy.read_json(results / "protocol_v2.json"),     # demo F (may be null)
        },
        "job": job.info() if job else None,
    }


def _audit(app, action: str, job_id: str, details: dict):
    try:
        with app.state.sessionmaker() as db:
            audit.append(db, ACTOR, action, "job", job_id, details)
    except Exception:  # noqa: BLE001 - the demo must keep working even if the database is down
        log.exception("could not write the audit event %s", action)


@router.get("/api/state", summary="Everything needed to render every panel (DemoState)")
def get_state(request: Request):
    return v1_json(demo_state(request.app))


@router.get("/api/steps", summary="Step catalogue: labels, durations, timeouts, confirmations (StepsResponse)")
def get_steps(request: Request):
    s = request.app.state.settings
    return v1_json({"api_version": legacy.API_VERSION, "mode": "simulate" if s.simulate else "live",
                    "steps": [{"id": k, **v} for k, v in legacy.STEP_INFO.items()]})


@router.post("/api/run", status_code=202, response_model=JobInfo, responses=V1_ERRORS,
             summary="Start a demo step (one job at a time: 409 while another runs)",
             openapi_extra={"requestBody": {"required": True,
                                            "content": {"application/json": {"schema": RunRequest.model_json_schema()}}}})
async def run_step(request: Request):
    body, msg = legacy.parse_object(await request.body())
    if msg:
        return v1_error(400, msg)
    step = body.get("step")
    if not isinstance(step, str) or step not in legacy.STEPS:
        return v1_error(400, f"unknown step {step!r}")
    try:
        tries = int(body.get("tries", legacy.DEFAULT_TRIES))
    except (TypeError, ValueError):
        tries = -1
    if tries not in legacy.TRIES_ALLOWED:
        return v1_error(400, f"tries must be one of {legacy.TRIES_ALLOWED}")
    manager = request.app.state.jobs
    try:
        job = manager.submit(step, tries, source="v1")
    except Busy as b:
        return v1_error(409, "another demo is running", job=b.job.info())
    mode = "SIMULATE " if request.app.state.settings.simulate else ""
    log.info("%srun %s (job %s)", mode, step, job.id, extra={"job_id": job.id, "step": step, "event": "demo.run"})
    await run_in_threadpool(_audit, request.app, "demo.run", job.id, {"step": step, "tries": tries,
                                                                      "simulated": job.simulated})
    return v1_json(job.info(), 202)


@router.post("/api/jobs/{job_id}/cancel", status_code=202, response_model=JobInfo, responses=V1_ERRORS,
             summary="Stop a running job (kills its process tree); body {} or empty")
async def cancel_job(job_id: str, request: Request):
    _, msg = legacy.parse_object(await request.body())
    if msg:
        return v1_error(400, msg)
    app = request.app
    job, stopped = await run_in_threadpool(app.state.jobs.cancel, job_id)
    if job is None:
        row, _ = await run_in_threadpool(db_job, app.state.sessionmaker, job_id)
        if row is None:
            return v1_error(404, "unknown job")
        return v1_error(409, "job not running", job=row_info(row))
    if not stopped:
        return v1_error(409, "job not running", job=job.info())
    log.info("cancel %s (job %s)", job.step, job.id, extra={"job_id": job.id, "event": "demo.cancel"})
    await run_in_threadpool(_audit, app, "demo.cancel", job.id, {"step": job.step})
    return v1_json(job.info(), 202)


@router.get("/api/jobs/{job_id}", response_model=JobDetail, responses={404: {"model": ErrorBody}},
            summary="Job status and all output so far")
async def get_job(job_id: str, request: Request):
    job = request.app.state.jobs.get(job_id)
    if job is not None:
        with job.cond:
            lines = list(job.lines)
        return v1_json({**job.info(), "output": lines})
    row, lines = await run_in_threadpool(db_job, request.app.state.sessionmaker, job_id)
    if row is None:
        return v1_error(404, "unknown job")
    return v1_json({**row_info(row), "output": lines})


def _frames(lines, start):
    return "".join(f"id: {i}\ndata: {json.dumps(line)}\n\n" for i, line in enumerate(lines, start=start))


async def _live_stream(job, sent: int, settings):
    last = time.monotonic()
    while True:
        with job.cond:
            new, done = job.lines[sent:], job.done
        if new:
            yield _frames(new, sent)
            sent += len(new)
            last = time.monotonic()
        if done and sent >= len(job.lines):
            yield f"event: done\ndata: {json.dumps(job.info())}\n\n"
            return
        if not new and time.monotonic() - last >= settings.sse_keepalive:
            yield ": keepalive\n\n"
            last = time.monotonic()
        await asyncio.sleep(settings.sse_poll)


async def _replay_stream(row, lines, sent: int):
    if lines[sent:]:
        yield _frames(lines[sent:], sent)
    yield f"event: done\ndata: {json.dumps(row_info(row))}\n\n"


@router.get("/api/jobs/{job_id}/stream", summary="Live output as Server-Sent Events (resumes after Last-Event-ID)",
            responses={200: {"content": {"text/event-stream": {}}}, 404: {"model": ErrorBody}})
async def stream_job(job_id: str, request: Request):
    try:
        sent = max(0, int(request.headers.get("last-event-id", "-1")) + 1)
    except ValueError:
        sent = 0
    headers = {"Cache-Control": "no-cache", "Connection": "close", "X-Accel-Buffering": "no"}
    job = request.app.state.jobs.get(job_id)
    if job is not None:
        gen = _live_stream(job, sent, request.app.state.settings)
    else:
        row, lines = await run_in_threadpool(db_job, request.app.state.sessionmaker, job_id)
        if row is None:
            return v1_error(404, "unknown job")
        gen = _replay_stream(row, lines, sent)
    return StreamingResponse(gen, media_type="text/event-stream", headers=headers)
