"""Job runner (API-04), built on demo/server.py's Job and SimJob.

Reused unchanged from the demo server: the step catalogue and per-step timeouts, Job.run() (crash-safe:
whatever happens the job ends in finish(), so the server never stays busy), the timeout watchdog (code -3),
cancel() (kills the whole process tree, code -2), and simulate mode's choice of recorded log.
Added here:
  * persistence: every job and every output line goes to the jobs / job_logs tables, through one writer
    thread that batches inserts (a slow database never slows a job down);
  * a FIFO queue for v2 jobs (one GPU-heavy job at a time); v1's POST /api/run keeps its 409;
  * crash recovery: jobs a previous process left queued/running are marked `interrupted` at start-up.
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, update

from . import legacy
from .config import DEMO
from .logs import log
from .models import JobLog, JobRow

FINAL = ("succeeded", "failed", "cancelled", "timed_out", "interrupted")
MEMORY_JOBS = 200                # finished jobs kept in memory; older ones are served from the database


def status_of(job) -> str:
    if not job.done:
        return "queued" if getattr(job, "queued", False) else "running"
    if job.cancelled:
        return "cancelled"
    if job.timed_out:
        return "timed_out"
    return "succeeded" if job.code == 0 else "failed"


def row_info(row: JobRow) -> dict:
    """v1 JobInfo for a job known only from the database."""
    return {"id": row.id, "step": row.step, "running": row.status in ("queued", "running"), "code": row.code,
            "started": row.started, "ended": row.ended, "lines": row.lines, "cancelled": row.cancelled,
            "timed_out": row.timed_out}


# ---------------------------------------------------------------------------------------------- persistence
class JobStore:
    """Single writer thread for jobs and job_logs. Operations are applied in order, in batches."""

    def __init__(self, session_factory):
        self.sf = session_factory
        self.q: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._loop, name="job-store", daemon=True)
        self.thread.start()

    def put(self, *op):
        self.q.put(op)

    def flush(self, timeout: float = 10.0) -> bool:
        ev = threading.Event()
        self.q.put(("barrier", ev))
        return ev.wait(timeout)

    def close(self, timeout: float = 10.0):
        self.flush(timeout)
        self.q.put(("stop",))
        self.thread.join(timeout)

    def _loop(self):
        while True:
            batch = [self.q.get()]
            while len(batch) < 500:
                try:
                    batch.append(self.q.get_nowait())
                except queue.Empty:
                    break
            stop = any(op[0] == "stop" for op in batch)
            work = [op for op in batch if op[0] not in ("barrier", "stop")]
            if work:
                self._apply_batch(work)
            for op in batch:
                if op[0] == "barrier":
                    op[1].set()
            if stop:
                return

    def _apply_batch(self, ops):
        try:
            with self.sf() as s, s.begin():
                for op in ops:
                    self._apply(s, op)
            return
        except Exception:  # noqa: BLE001 - retry one by one so one bad op can't lose the batch
            pass
        for op in ops:
            try:
                with self.sf() as s, s.begin():
                    self._apply(s, op)
            except Exception as e:  # noqa: BLE001 - persistence must never break a running job
                log.warning("job store: could not persist %s (%s)", op[0], e.__class__.__name__)

    @staticmethod
    def _apply(s, op):
        kind = op[0]
        if kind == "create":
            s.add(JobRow(**op[1]))
        elif kind == "start":
            s.execute(update(JobRow).where(JobRow.id == op[1]).values(status="running", started=op[2]))
        elif kind == "log":
            s.add(JobLog(job_id=op[1], seq=op[2], line=op[3]))
        elif kind == "finish":
            info, status = op[2], op[3]
            s.execute(update(JobRow).where(JobRow.id == op[1]).values(
                status=status, code=info["code"], ended=info["ended"], lines=info["lines"],
                cancelled=info["cancelled"], timed_out=info["timed_out"]))


# ---------------------------------------------------------------------------------------------- job classes
class PersistentMixin:
    """Mixed into demo/server.py's Job / SimJob: every line and the final state are persisted."""
    manager: "JobManager"
    queued = False

    def push(self, line):
        line = legacy.scrub_paths(line)            # tracebacks/warnings print absolute paths (FIX-15)
        with self.cond:
            self.lines.append(line)
            seq = len(self.lines) - 1
            self.cond.notify_all()
        self.manager.store.put("log", self.id, seq, line)

    def finish(self, code):
        super().finish(code)
        try:
            self.manager.store.put("finish", self.id, self.info(), status_of(self))
        except Exception:  # noqa: BLE001
            pass
        self.manager._finished(self)


class LiveJob(PersistentMixin, legacy.Job):
    """Runs the step's demo scripts, exactly like demo/server.py (same cwd, env, noise filter, path scrub);
    the interpreter and results folder come from the settings."""

    def _run(self) -> int:
        s = self.manager.settings
        code = 0
        with open(Path(s.results_dir) / "web_job_log.txt", "a", encoding="utf-8") as logf:
            logf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} job {self.id} step={self.step}\n")
            for cmd in self.cmds:
                if self.stop.is_set():
                    break
                self.push(f"$ python {' '.join(cmd)}")
                try:
                    self.proc = subprocess.Popen([s.python_exe, "-u", *cmd], cwd=DEMO, stdout=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                                 errors="replace", env=legacy.child_env(), **legacy.POPEN_GROUP)
                except OSError as e:
                    self.push(f"failed to start: {e}")
                    return 1
                if self.stop.is_set():          # cancelled while the process was starting
                    self.kill()
                with self.proc.stdout:
                    for line in self.proc.stdout:
                        logf.write(legacy.scrub_paths(line))
                        if not legacy.is_noise(line):
                            self.push(line.rstrip("\n"))
                code = self.proc.wait()
                if self.stop.is_set():
                    break
                if code != 0:
                    self.push(f"{cmd[0]} failed (exit {code})")
                    break
        return code


class SimJob(PersistentMixin, legacy.SimJob):
    """--simulate: replays contract/fixtures/logs/<step>.log (demo/server.py's choice of log, incl. `tries`)."""

    def _run(self) -> int:
        delay = self.manager.settings.sim_delay
        logfile, wanted = legacy.sim_log_for(self.step, self.tries)
        self.push(f"[SIMULATED] Replaying recorded output of step '{self.step}'. Nothing is executed; results/ is unchanged.")
        if logfile is None:
            self.push(f"[SIMULATED] no recorded log at {legacy.rel(wanted)}")
            return 1
        note = "" if logfile == wanted else \
            f" (no recording for tries={self.tries:,}; numbers below are from a {legacy.DEFAULT_TRIES:,}-try run)"
        self.push(f"[SIMULATED] Replaying {legacy.rel(logfile)}{note}")
        for line in logfile.read_text(encoding="utf-8").splitlines():
            self.push(line)
            if self.stop.wait((0.5 if line.startswith("$ python") else 0.025) * delay):
                return 1                       # cancelled or timed out; run() sets the final code
        return 0


# ---------------------------------------------------------------------------------------------- manager
class Busy(Exception):
    def __init__(self, job):
        self.job = job


class JobManager:
    def __init__(self, settings, store: JobStore, on_finished=None):
        self.settings, self.store, self.on_finished = settings, store, on_finished
        self.jobs: dict[str, legacy.Job] = {}
        self.current = None                    # the most recently started job (v1 `state.job`)
        self.queue: deque = deque()
        self.lock = threading.RLock()
        self.threads: list[threading.Thread] = []

    def get(self, job_id: str):
        return self.jobs.get(job_id)

    def busy(self) -> bool:
        return self.current is not None and not self.current.done

    def submit(self, step: str, tries: int = legacy.DEFAULT_TRIES, *, queue_if_busy: bool = False,
               user_id: int | None = None, source: str = "v1"):
        """Start a job now, or (v2) queue it behind the running one. Raises Busy (v1's 409) otherwise."""
        with self.lock:
            busy = self.busy()
            if busy and not queue_if_busy:
                raise Busy(self.current)
            cmds = [[c.replace("{tries}", str(tries)) for c in cmd] for cmd in legacy.STEPS[step]]
            cls = SimJob if self.settings.simulate else LiveJob
            job = cls(step, cmds, tries=tries, timeout=legacy.STEP_INFO[step]["timeout"])
            job.manager, job.source, job.user_id = self, source, user_id
            job.simulated = bool(self.settings.simulate)
            job.queued = busy
            self.jobs[job.id] = job
            self._prune()
            self.store.put("create", {
                "id": job.id, "step": step, "kind": "demo", "source": source, "status": status_of(job),
                "code": None, "simulated": job.simulated, "tries": tries, "cancelled": False, "timed_out": False,
                "timeout": job.timeout, "started": job.started, "ended": None, "lines": 0, "submitted_by": user_id,
                "created_at": datetime.now(timezone.utc)})
            if busy:
                self.queue.append(job)
            else:
                self._start(job)
        log.info("job %s submitted", job.id, extra={"job_id": job.id, "step": step, "event": "job.submitted"})
        return job

    def _start(self, job):
        job.queued = False
        job.started = time.time()
        self.current = job
        self.store.put("start", job.id, job.started)
        t = threading.Thread(target=job.run, daemon=True, name=f"job-{job.id}")
        self.threads = [x for x in self.threads if x.is_alive()] + [t]
        t.start()

    def _finished(self, job):
        try:
            with self.lock:
                if not self.busy():
                    while self.queue:
                        nxt = self.queue.popleft()
                        if not nxt.done:
                            self._start(nxt)
                            break
            if self.on_finished:
                self.on_finished(job)
        except Exception:  # noqa: BLE001 - a callback failure must not leave the queue stuck
            log.exception("job finish hook failed", extra={"job_id": job.id})

    def cancel(self, job_id: str):
        """(job, True) if it was stopped; (job, False) if it had already finished; (None, False) if unknown."""
        job = self.jobs.get(job_id)
        if job is None:
            return None, False
        with self.lock:
            if job in self.queue:              # never started: finish it here
                self.queue.remove(job)
                job.cancelled = True
                job.push("[server] cancelled")
                job.finish(legacy.CODE_CANCELLED)
                return job, True
        if not job.cancel():
            return job, False
        job.wait(legacy.CANCEL_WAIT)           # usually ends well within a second; the SSE "done" event follows
        return job, True

    def _prune(self):
        if len(self.jobs) <= MEMORY_JOBS:
            return
        for jid in [j for j, job in self.jobs.items() if job.done and job is not self.current][: len(self.jobs) - MEMORY_JOBS]:
            del self.jobs[jid]

    def shutdown(self, wait: float = legacy.CANCEL_WAIT):
        with self.lock:
            queued = list(self.queue)
        for job in queued:
            self.cancel(job.id)
        if self.current is not None and self.current.cancel():
            self.current.wait(wait)
        for t in list(self.threads):            # let finish hooks (history, audit) complete
            t.join(wait)
        self.store.flush()


def recover_interrupted(session_factory) -> list[str]:
    """Jobs a previous server process left queued or running can't still be running: mark them final."""
    with session_factory() as s:
        rows = s.scalars(select(JobRow).where(JobRow.status.in_(("queued", "running")))).all()
        ids = []
        for row in rows:
            last = s.scalar(select(func.max(JobLog.seq)).where(JobLog.job_id == row.id))
            n = 0 if last is None else last + 1
            row.status, row.code, row.ended = "interrupted", 1, time.time()
            s.add(JobLog(job_id=row.id, seq=n, line="[server] interrupted: the server stopped before this job finished"))
            row.lines = n + 1
            ids.append(row.id)
        s.commit()
    return ids


def db_job(session_factory, job_id: str):
    """(JobRow, [lines]) of a job from the database, or (None, None)."""
    with session_factory() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            return None, None
        lines = s.scalars(select(JobLog.line).where(JobLog.job_id == job_id).order_by(JobLog.seq)).all()
        return row, list(lines)
