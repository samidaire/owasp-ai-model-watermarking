"""API-02 / API-04: v1 parity of the FastAPI backend with demo/server.py.

tests/test_server.py, ported: the app runs under a real uvicorn on an ephemeral port in simulate mode, and
"live" jobs are exercised with tiny `python -c` commands, so no torch/ezkl is needed. Added: SSE resume,
keepalive and close-after-done, persisted job logs, restart recovery, a killed child process, CORS preflight.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from backend.app import legacy  # noqa: E402
from backend.app import jobs as jobs_mod  # noqa: E402
from backend.app import v1  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.testing import LiveServer, call, database, make_settings  # noqa: E402

DEMO = Path(__file__).resolve().parents[1] / "demo"


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("v1")
    with database() as url:
        app = create_app(make_settings(tmp, url))
        with LiveServer(app) as live:
            yield live


@pytest.fixture
def port(srv):
    return srv.port


@pytest.fixture
def app(srv):
    return srv.app


@pytest.fixture(autouse=True)
def no_job_left_running(request):
    yield
    if "srv" in request.fixturenames:
        mgr = request.getfixturevalue("srv").app.state.jobs
        if mgr.current is not None and mgr.current.cancel():
            mgr.current.wait(5)       # never let one test's job block the next one (409)


def run(port, step="forgery", **extra):
    return call(port, "POST", "/api/run", body={"step": step, **extra})


def cancel(port, job_id, **kw):
    kw.setdefault("body", {})
    return call(port, "POST", f"/api/jobs/{job_id}/cancel", **kw)


def wait_done(port, job_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        status, _, job = call(port, "GET", f"/api/jobs/{job_id}")
        assert status == 200
        if not job["running"]:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running after {timeout}s")


def wait_for_line(port, job_id, prefix, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        _, _, job = call(port, "GET", f"/api/jobs/{job_id}")
        if any(line.startswith(prefix) for line in job["output"]):
            return job
        if not job["running"]:
            raise AssertionError(f"job ended before printing {prefix!r}: {job['output']}")
        time.sleep(0.05)
    raise AssertionError(f"{prefix!r} not printed within {timeout}s")


# ---------------------------------------------------------------------------------- read-only API
def test_state_works_in_simulate_mode(port):
    status, headers, s = call(port, "GET", "/api/state")
    assert status == 200 and s["api_version"] == 1 and s["mode"] == "simulate"
    assert set(s["results"]) >= {"train", "attacks", "forgery", "committed_seed", "vk_crosscheck", "ezkl",
                                 "protocol_v2"}
    assert headers["Cache-Control"] == "no-store"


def test_steps_include_timeouts(port):
    status, _, body = call(port, "GET", "/api/steps")
    assert status == 200
    steps = {s["id"]: s for s in body["steps"]}
    for s in steps.values():
        assert isinstance(s["timeout"], int) and s["timeout"] >= 120
        assert s["timeout"] == (1800 if s["id"] == "zk_hashed" else max(120, 10 * s["seconds"]))
    assert steps["zk_hashed"]["timeout"] == 1800


def test_bad_result_files_become_null(port, app, tmp_path, monkeypatch):
    (tmp_path / "train.json").write_text("{\"partial\": ", encoding="utf-8")
    (tmp_path / "public_commitment.json").write_text("[1, 2", encoding="utf-8")
    (tmp_path / "attacks.json").write_bytes(b"\xff\xfe\x00garbage")
    (tmp_path / "forgery.json").write_text("[]", encoding="utf-8")         # valid JSON, served as-is
    monkeypatch.setattr(app.state.settings, "results_dir", tmp_path)
    status, _, s = call(port, "GET", "/api/state")
    assert status == 200
    assert s["commitment"] is None and s["results"]["train"] is None and s["results"]["attacks"] is None
    assert s["results"]["forgery"] == []


def test_results_are_not_cached(port):
    status, headers, _ = call(port, "GET", "/results/train.json")
    assert status == 200 and headers["Cache-Control"] == "no-cache"
    assert headers["Content-Type"].startswith("application/json")


@pytest.mark.parametrize("path", ["/results/../server.py", "/results/..%2fserver.py", "/results/..%2Fserver.py",
                                  "/results/..\\server.py", "/results/..%5cserver.py", "/results/../../README.md",
                                  "/results/..\\..\\README.md", "/results/C:/Windows/win.ini", "/results//etc/passwd",
                                  "/results/../ckpt/owner_secret.json", "/results/%00.json"])
def test_results_path_traversal_is_404(port, path):
    status, _, body = call(port, "GET", path)
    assert status == 404, (path, body)


def test_unknown_job_and_wrong_methods(port):
    assert call(port, "GET", "/api/jobs/nope")[0] == 404
    assert call(port, "GET", "/api/jobs/nope")[2] == {"error": "unknown job"}
    assert cancel(port, "nope")[0] == 404
    assert call(port, "POST", "/api/nope", body={})[0] == 404
    assert call(port, "GET", "/api/nope")[2] == {"error": "not found"}


# ---------------------------------------------------------------------------------- request guards
@pytest.mark.parametrize("raw", ["[1, 2]", "\"forgery\"", "42", "null", "true", "{bad json", "\xff"])
def test_run_rejects_non_object_or_bad_json(port, raw):
    status, _, body = call(port, "POST", "/api/run", body=raw.encode("latin-1"),
                           headers={"Content-Type": "application/json"})
    assert status == 400 and "error" in body


def test_run_rejects_bad_step_and_tries(port):
    assert run(port, step=["forgery"])[0] == 400
    assert run(port, step="rm -rf /")[0] == 400
    assert run(port, step="committed", tries=12345)[0] == 400
    assert run(port, step="committed", tries=True)[0] == 400


def test_foreign_origin_is_403(port):
    for origin in ("http://evil.example", "http://[::1]evil.com", "http://localhost:evil", "null"):
        status, _, body = call(port, "POST", "/api/run", body={"step": "forgery"}, headers={"Origin": origin})
        assert status == 403 and body == {"error": "origin not allowed"}, origin
    status, _, _ = cancel(port, "whatever", headers={"Origin": "http://evil.example"})
    assert status == 403


def test_non_json_content_type_is_415(port):
    status, _, body = call(port, "POST", "/api/run", body=b'{"step": "forgery"}', headers={"Content-Type": "text/plain"})
    assert status == 415 and body == {"error": "Content-Type must be application/json"}
    status, _, _ = call(port, "POST", "/api/jobs/x/cancel", body=b"{}", headers={"Content-Type": "text/plain"})
    assert status == 415
    status, _, _ = call(port, "POST", "/api/run", body=b'step=forgery',
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 415


def test_large_body_is_413(port):
    big = json.dumps({"step": "forgery", "pad": "x" * (legacy.MAX_BODY + 10)})
    status, _, body = call(port, "POST", "/api/run", body=big, headers={"Content-Type": "application/json"})
    assert status == 413 and body == {"error": "request body too large"}


@pytest.mark.parametrize("host", ["[::1]evil.com", "localhost:evil", "evil.com", "localhost.evil.com:80",
                                  "127.0.0.1:80:80", "[::1", "", "user@localhost"])
def test_malformed_or_foreign_host_is_403(port, host):
    assert call(port, "GET", "/api/state", host=host)[0] == 403
    assert call(port, "POST", "/api/run", body={"step": "forgery"}, host=host)[0] == 403
    assert call(port, "GET", "/", host=host)[0] == 403


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST:8765", "127.0.0.1:1", "[::1]:8765", "[::1]"])
def test_local_hosts_are_accepted(port, host):
    assert call(port, "GET", "/api/state", host=host)[0] == 200


def test_cors_only_for_local_origins(port):
    status, headers, _ = call(port, "GET", "/api/state", headers={"Origin": "http://localhost:5173"})
    assert status == 200 and headers["access-control-allow-origin"] == "http://localhost:5173"
    status, headers, _ = call(port, "GET", "/api/state", headers={"Origin": "http://evil.example"})
    assert status == 200 and "access-control-allow-origin" not in headers
    status, headers, _ = call(port, "OPTIONS", "/api/run", headers={
        "Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert status == 204 and headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "POST" in headers["access-control-allow-methods"]
    assert "Content-Type" in headers["access-control-allow-headers"]
    assert call(port, "OPTIONS", "/api/run", headers={"Origin": "http://evil.example"})[0] == 403
    assert call(port, "OPTIONS", "/api/run")[0] == 403


def test_gpu_probe_reports_the_last_stderr_line(app, monkeypatch):
    try:
        import torch  # noqa: F401
        has_torch = True
    except ImportError:
        has_torch = False
    s = app.state.settings
    if not has_torch:
        env = v1.probe_env(s)
        assert env["status"] == "error" and env["error"].endswith("ModuleNotFoundError: No module named 'torch'")
    monkeypatch.setattr(s, "demo_python", str(DEMO / "no-such-python.exe"))
    env = v1.probe_env(s)
    assert env["status"] == "error" and "FileNotFoundError" in env["error"]


def test_host_and_origin_parsers():
    from backend.app.security import host_allowed, origin_allowed
    assert not host_allowed([b"[::1]evil.com"]) and not host_allowed([b"localhost:evil"])
    assert host_allowed([b"[::1]:8765"]) and host_allowed([b"Localhost:5173"]) and host_allowed([])
    assert not host_allowed([b"localhost", b"localhost"])
    assert origin_allowed("http://localhost:5173") and origin_allowed("http://[::1]:3000")
    assert not origin_allowed("http://[::1]evil.com") and not origin_allowed("http://localhost:evil")
    assert not origin_allowed("null") and not origin_allowed(None)


# ---------------------------------------------------------------------------------- job lifecycle (simulate)
def test_cancel_simulated_job_then_run_again(port):
    status, _, job = run(port)
    assert status == 202 and job["cancelled"] is False and job["timed_out"] is False
    status, _, busy = run(port, step="attacks")
    assert status == 409 and busy["job"]["id"] == job["id"] and busy["error"] == "another demo is running"

    status, _, info = cancel(port, job["id"])
    assert status == 202 and info["cancelled"] is True and info["timed_out"] is False
    final = wait_done(port, job["id"])
    assert final["code"] == -2 and final["cancelled"] is True
    assert final["output"][-1] == "[server] cancelled"

    status, _, again = cancel(port, job["id"])
    assert status == 409 and again["error"] == "job not running" and again["job"]["code"] == -2

    status, _, stream = call(port, "GET", f"/api/jobs/{job['id']}/stream")    # finished: replay + done
    done = json.loads(stream.decode().split("event: done\ndata: ", 1)[1])
    assert done["cancelled"] is True and done["code"] == -2

    status, _, nxt = run(port, step="attacks")                               # server is not wedged
    assert status == 202 and nxt["id"] != job["id"]
    _, _, s = call(port, "GET", "/api/state")
    assert s["job"]["id"] == nxt["id"] and s["job"]["running"] is True


def test_crashing_runner_still_finishes(port, monkeypatch):
    def boom(self):
        self.push("about to crash")
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs_mod.SimJob, "_run", boom)
    status, _, job = run(port)
    assert status == 202
    final = wait_done(port, job["id"])
    assert final["code"] == 1 and not final["cancelled"] and not final["timed_out"]
    assert any("RuntimeError: boom" in line for line in final["output"])
    monkeypatch.undo()
    status, _, nxt = run(port)
    assert status == 202


def test_simulated_job_times_out(port, monkeypatch):
    monkeypatch.setitem(legacy.STEP_INFO["forgery"], "timeout", 0.3)
    status, _, job = run(port)
    assert status == 202
    final = wait_done(port, job["id"])
    assert final["code"] == -3 and final["timed_out"] is True and final["cancelled"] is False
    assert run(port)[0] == 202


def test_simulate_honours_tries(port):
    status, _, job = run(port, step="committed", tries=100000)
    assert status == 202
    detail = wait_for_line(port, job["id"], "[SIMULATED] Replaying contract/fixtures/logs/")
    line = next(x for x in detail["output"] if x.startswith("[SIMULATED] Replaying contract/"))
    if (legacy.SIM_LOGS / "committed_100000.log").exists():
        assert line.endswith("committed_100000.log")
    else:
        assert "committed.log" in line and "no recording for tries=100,000" in line
    cancel(port, job["id"])

    status, _, job = run(port, step="committed", tries=20000)
    detail = wait_for_line(port, job["id"], "[SIMULATED] Replaying contract/fixtures/logs/")
    assert "[SIMULATED] Replaying contract/fixtures/logs/committed.log" in detail["output"]


def test_protocol_v2_step_mirrors_the_demo_server(port):
    """Demo F (main 7e4cc08): same catalogue entry as demo/server.py, replayable in simulate mode."""
    _, _, body = call(port, "GET", "/api/steps")
    steps = {s["id"]: s for s in body["steps"]}
    assert set(steps) == set(legacy.STEPS)
    assert steps["protocol_v2"]["panel"] == "F" and "protocol_v2.json" in steps["protocol_v2"]["writes"]
    status, _, job = run(port, step="protocol_v2")
    assert status == 202
    wait_for_line(port, job["id"], "[SIMULATED] Replaying contract/fixtures/logs/protocol_v2.log")


def test_models_and_model_tests_mirror_the_demo_server(port):
    """"Model under test" (main 842bd55): GET /api/models and results.model_tests, as demo/server.py serves them."""
    status, _, body = call(port, "GET", "/api/models")
    assert status == 200 and body == {"api_version": 1, "models": legacy.model_catalogue.catalogue()}
    _, _, s = call(port, "GET", "/api/state")
    assert s["results"]["model_tests"]["clean"]["verdict"] == "no_proof"


def test_model_test_needs_a_known_model(port):
    for bad in (None, "", "../../secrets/owner.key", "file:nope.pt", 7):
        extra = {} if bad is None else {"model": bad}
        status, _, err = run(port, step="model_test", **extra)
        assert status == 400 and "unknown model" in err["error"], bad


def test_model_test_replays_that_models_recording_and_persists_the_model(port, app):
    status, _, job = run(port, step="model_test", model="permute")
    assert status == 202 and job["model"] == "permute"
    done = wait_done(port, job["id"], timeout=20)
    assert done["code"] == 0 and done["model"] == "permute"
    out = "\n".join(done["output"])
    assert "MODEL TEST: watermarked_v2 · channels permuted" in out and "NOT PROVEN" in out
    mgr = app.state.jobs
    for t in list(mgr.threads):
        t.join(5)
    mgr.store.flush()
    mgr.jobs.pop(job["id"])                          # served from the database now
    status, _, detail = call(port, "GET", f"/api/jobs/{job['id']}")
    assert status == 200 and detail["model"] == "permute" and detail["output"] == done["output"]


def test_a_users_file_is_listed_but_not_replayed_in_simulate_mode(port):
    mc = legacy.model_catalogue
    mc.USER_DIR.mkdir(exist_ok=True)
    f = mc.USER_DIR / "pytest_backend_dropped_model.pt"
    f.write_bytes(b"not really a model")
    try:
        _, _, body = call(port, "GET", "/api/models")
        assert "file:pytest_backend_dropped_model.pt" in [m["id"] for m in body["models"]]
        status, _, job = run(port, step="model_test", model="file:pytest_backend_dropped_model.pt")
        assert status == 202
        done = wait_done(port, job["id"], timeout=20)
        assert done["code"] == 1 and any("no recording" in line for line in done["output"])
    finally:
        f.unlink()


# ---------------------------------------------------------------------------------- SSE
def _sse_events(raw: bytes):
    events = []
    for block in raw.decode().split("\n\n"):
        if not block.strip():
            continue
        ev = {"comment": [], "event": None, "id": None, "data": None}
        for line in block.split("\n"):
            if line.startswith(":"):
                ev["comment"].append(line)
            elif line.startswith("id: "):
                ev["id"] = int(line[4:])
            elif line.startswith("event: "):
                ev["event"] = line[7:]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[6:])
        events.append(ev)
    return events


def test_stream_replays_resumes_and_closes_after_done(port):
    status, _, job = run(port)
    final = wait_done(port, job["id"], timeout=20)
    status, headers, raw = call(port, "GET", f"/api/jobs/{job['id']}/stream")
    assert status == 200 and headers["Content-Type"].startswith("text/event-stream")
    assert headers["Cache-Control"] == "no-cache" and headers["Connection"] == "close"
    events = _sse_events(raw)
    lines = [e for e in events if e["event"] is None and e["data"] is not None]
    assert [e["id"] for e in lines] == list(range(final["lines"]))
    assert [e["data"] for e in lines] == final["output"]
    assert events[-1]["event"] == "done" and events[-1]["data"]["code"] == final["code"]

    # Reconnect with Last-Event-ID: resume after that line, no duplicates
    status, _, raw = call(port, "GET", f"/api/jobs/{job['id']}/stream", headers={"Last-Event-ID": "9"})
    resumed = [e for e in _sse_events(raw) if e["event"] is None and e["data"] is not None]
    assert [e["id"] for e in resumed] == list(range(10, final["lines"]))
    status, _, raw = call(port, "GET", f"/api/jobs/{job['id']}/stream", headers={"Last-Event-ID": "junk"})
    assert _sse_events(raw)[0]["id"] == 0


def test_live_stream_follows_a_running_job(port):
    status, _, job = run(port)
    status, _, raw = call(port, "GET", f"/api/jobs/{job['id']}/stream", timeout=30)
    events = _sse_events(raw)
    assert events[-1]["event"] == "done" and events[-1]["data"]["code"] == 0
    assert events[0]["data"].startswith("[SIMULATED]")


# ---------------------------------------------------------------------------------- live jobs (real processes)
@pytest.fixture
def live(app, monkeypatch, tmp_path):
    monkeypatch.setattr(app.state.settings, "simulate", False)
    monkeypatch.setattr(app.state.settings, "results_dir", tmp_path)      # web_job_log.txt goes here


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        return "\nState:\tZ" not in Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return True


def _kill(pid):
    subprocess.run(["taskkill", "/F", "/PID", str(pid)] if os.name == "nt" else ["kill", "-9", str(pid)],
                   capture_output=True)


def test_live_cancel_kills_the_process_tree(port, live, monkeypatch):
    code = ("import subprocess, sys, time\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=sys.stdout, stderr=sys.stderr)\n"
            "print('GPID', g.pid, flush=True)\n"
            "time.sleep(30)\n")
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", code]])
    status, _, job = run(port)
    assert status == 202
    detail = wait_for_line(port, job["id"], "GPID ")
    gpid = int(next(x for x in detail["output"] if x.startswith("GPID ")).split()[1])
    try:
        t0 = time.time()
        status, _, info = cancel(port, job["id"])
        assert status == 202 and info["cancelled"] is True
        final = wait_done(port, job["id"], timeout=10)
        assert final["code"] == -2 and time.time() - t0 < 10
        for _ in range(50):
            if not _alive(gpid):
                break
            time.sleep(0.1)
        assert not _alive(gpid)
        assert run(port)[0] == 202
    finally:
        if _alive(gpid):
            _kill(gpid)


def test_killed_child_process_still_finishes(port, live, monkeypatch):
    """API-04 'killed job': the demo process dies from outside; the job ends non-zero and the server is free."""
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", "import os, time; print('PID', os.getpid(), flush=True); "
                                                          "time.sleep(30)"]])
    status, _, job = run(port)
    detail = wait_for_line(port, job["id"], "PID ")
    pid = int(next(x for x in detail["output"] if x.startswith("PID ")).split()[1])
    _kill(pid)
    final = wait_done(port, job["id"], timeout=15)
    assert final["code"] not in (0, None, -2, -3) and not final["cancelled"] and not final["timed_out"]
    assert any("failed (exit" in line for line in final["output"])
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", "print('fine')"]])
    status, _, job = run(port)
    assert status == 202 and wait_done(port, job["id"])["code"] == 0


def test_live_job_times_out(port, live, monkeypatch):
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", "import time; print('working', flush=True); time.sleep(30)"]])
    monkeypatch.setitem(legacy.STEP_INFO["forgery"], "timeout", 1)
    status, _, job = run(port)
    assert status == 202
    final = wait_done(port, job["id"], timeout=15)
    assert final["code"] == -3 and final["timed_out"] is True
    assert any("timed out after 1 s" in line for line in final["output"])


def test_live_job_success_and_failure_codes(port, live, monkeypatch):
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", "print('ok')"], ["-c", "import sys; sys.exit(3)"],
                                                  ["-c", "print('never runs')"]])
    status, _, job = run(port)
    final = wait_done(port, job["id"])
    assert final["code"] == 3 and not final["cancelled"] and not final["timed_out"]
    assert "ok" in final["output"] and "never runs" not in final["output"]


def test_keepalive_while_a_job_is_quiet(port, app, live, monkeypatch):
    monkeypatch.setattr(app.state.settings, "sse_keepalive", 0.2)
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", "import time; print('a', flush=True); time.sleep(1.2); "
                                                          "print('b', flush=True)"]])
    status, _, job = run(port)
    status, _, raw = call(port, "GET", f"/api/jobs/{job['id']}/stream", timeout=30)
    events = _sse_events(raw)
    assert any(e["comment"] == [": keepalive"] for e in events)
    assert [e["data"] for e in events if e["event"] is None and e["data"] is not None][-2:] == ["a", "b"]
    assert events[-1]["event"] == "done"


def test_absolute_paths_are_scrubbed_from_output_and_log(port, live, monkeypatch, tmp_path):
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", "import os; print('cwd', os.getcwd())"]])
    status, _, job = run(port)
    final = wait_done(port, job["id"])
    assert final["code"] == 0 and "cwd demo" in final["output"]
    log = (tmp_path / "web_job_log.txt").read_text(encoding="utf-8")
    assert "cwd demo" in log and str(DEMO.parent) not in log


def test_simulated_replay_hides_recorded_personal_paths(port):
    status, _, job = run(port, step="zk")
    detail = wait_for_line(port, job["id"], "  Saved demo", timeout=15)
    assert not any("Users" in line for line in detail["output"])


def test_live_job_crash_in_log_writer_still_finishes(port, live, monkeypatch, tmp_path):
    (tmp_path / "web_job_log.txt").mkdir()                # open() for append fails -> exception in run()
    status, _, job = run(port)
    final = wait_done(port, job["id"])
    assert final["code"] == 1 and any("Error" in line for line in final["output"])
    (tmp_path / "web_job_log.txt").rmdir()
    monkeypatch.setitem(legacy.STEPS, "forgery", [["-c", "print('fine')"]])
    status, _, job = run(port)
    assert status == 202 and wait_done(port, job["id"])["code"] == 0


# ---------------------------------------------------------------------------------- persistence (API-04)
def test_jobs_and_logs_are_persisted_and_audited(port, app):
    from sqlalchemy import select

    from backend.app.models import AuditEvent, JobLog, JobRow
    status, _, job = run(port)
    final = wait_done(port, job["id"], timeout=20)
    mgr = app.state.jobs
    for t in list(mgr.threads):
        t.join(5)
    mgr.store.flush()
    with app.state.sessionmaker() as db:
        row = db.get(JobRow, job["id"])
        assert row.status == "succeeded" and row.code == 0 and row.lines == final["lines"] and row.simulated
        lines = db.scalars(select(JobLog.line).where(JobLog.job_id == job["id"]).order_by(JobLog.seq)).all()
        assert list(lines) == final["output"]
        actions = db.scalars(select(AuditEvent.action).where(AuditEvent.resource_id == job["id"])).all()
        assert "demo.run" in actions and "job.finished" in actions
    # forget the in-memory job: GET and the stream are served from the database
    mgr.jobs.pop(job["id"])
    status, _, detail = call(port, "GET", f"/api/jobs/{job['id']}")
    assert status == 200 and detail["output"] == final["output"] and detail["code"] == 0
    status, _, raw = call(port, "GET", f"/api/jobs/{job['id']}/stream", headers={"Last-Event-ID": "2"})
    ev = _sse_events(raw)
    assert ev[0]["id"] == 3 and ev[-1]["event"] == "done"
    assert cancel(port, job["id"])[0] == 409


def test_restart_marks_interrupted_jobs_final(tmp_path):
    """Crash-safety across restarts: a job the previous process left 'running' is final after start-up."""
    from fastapi.testclient import TestClient

    from backend.app.models import JobLog, JobRow
    with database() as url:
        settings = make_settings(tmp_path, url)
        app1 = create_app(settings)
        with TestClient(app1, base_url="http://127.0.0.1"):
            with app1.state.sessionmaker() as db:
                db.add(JobRow(id="deadbeef0001", step="attacks", kind="demo", source="v1", status="running",
                              simulated=False, tries=20000, cancelled=False, timed_out=False, started=time.time(),
                              lines=0))
                db.flush()
                db.add(JobLog(job_id="deadbeef0001", seq=0, line="$ python 02_attacks.py"))
                db.commit()
        app2 = create_app(settings)                      # "the server restarted"
        with TestClient(app2, base_url="http://127.0.0.1") as c:
            r = c.get("/api/jobs/deadbeef0001")
            assert r.status_code == 200
            j = r.json()
            assert j["running"] is False and j["code"] == 1
            assert j["output"] == ["$ python 02_attacks.py",
                                   "[server] interrupted: the server stopped before this job finished"]
            assert c.post("/api/run", json={"step": "forgery"}).status_code == 202


def test_sys_executable_is_the_default_demo_interpreter(app):
    assert app.state.settings.python_exe == (app.state.settings.demo_python or sys.executable)
