"""demo/server.py robustness (FIX-11). The server runs in-process on an ephemeral port in simulate mode;
"live" jobs are exercised with tiny `python -c` commands, so no torch/ezkl is needed."""
import http.client
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "demo"

_spec = importlib.util.spec_from_file_location("demo_server", DEMO / "server.py")
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


@pytest.fixture(scope="module")
def port():
    httpd = server.make_server(0, simulate=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address[1]
    server.stop_current_job()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def no_job_left_running():
    yield
    server.stop_current_job()         # never let one test's job block the next one (409)


def call(port, method, path, body=None, headers=None, host=None):
    """Raw HTTP call (no URL normalisation, explicit Host). Returns (status, headers, parsed body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    h = {"Host": f"127.0.0.1:{port}" if host is None else host}
    if isinstance(body, (dict, list)):
        body = json.dumps(body)
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    try:
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        try:
            parsed = json.loads(data)
        except ValueError:
            parsed = data
        return r.status, dict(r.getheaders()), parsed
    finally:
        conn.close()


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
    """Wait until the job printed a line starting with `prefix`."""
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
    assert set(s["results"]) >= {"train", "attacks", "forgery", "committed_seed", "vk_crosscheck", "ezkl"}


def test_steps_include_timeouts(port):
    status, _, body = call(port, "GET", "/api/steps")
    assert status == 200
    steps = {s["id"]: s for s in body["steps"]}
    for s in steps.values():
        assert isinstance(s["timeout"], int) and s["timeout"] >= 120
        assert s["timeout"] == (1800 if s["id"] == "zk_hashed" else max(120, 10 * s["seconds"]))
    assert steps["zk_hashed"]["timeout"] == 1800


def test_bad_result_files_become_null(port, tmp_path, monkeypatch):
    (tmp_path / "train.json").write_text("{\"partial\": ", encoding="utf-8")
    (tmp_path / "public_commitment.json").write_text("[1, 2", encoding="utf-8")
    (tmp_path / "attacks.json").write_bytes(b"\xff\xfe\x00garbage")
    (tmp_path / "forgery.json").write_text("[]", encoding="utf-8")         # valid JSON, served as-is
    monkeypatch.setattr(server, "RESULTS", tmp_path)
    status, _, s = call(port, "GET", "/api/state")
    assert status == 200
    assert s["commitment"] is None and s["results"]["train"] is None and s["results"]["attacks"] is None
    assert s["results"]["forgery"] == []


def test_results_are_not_cached(port):
    status, headers, _ = call(port, "GET", "/results/train.json")
    assert status == 200 and headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("path", ["/results/../server.py", "/results/..%2fserver.py", "/results/..%2Fserver.py",
                                  "/results/..\\server.py", "/results/..%5cserver.py", "/results/../../README.md",
                                  "/results/..\\..\\README.md", "/results/C:/Windows/win.ini", "/results//etc/passwd",
                                  "/results/../ckpt/owner_secret.json", "/results/%00.json"])
def test_results_path_traversal_is_404(port, path):
    status, _, body = call(port, "GET", path)
    assert status == 404, (path, body)


def test_unknown_job_and_wrong_methods(port):
    assert call(port, "GET", "/api/jobs/nope")[0] == 404
    assert cancel(port, "nope")[0] == 404
    assert call(port, "POST", "/api/nope", body={})[0] == 404


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


def test_foreign_origin_is_403(port):
    for origin in ("http://evil.example", "http://[::1]evil.com", "http://localhost:evil", "null"):
        status, _, _ = call(port, "POST", "/api/run", body={"step": "forgery"}, headers={"Origin": origin})
        assert status == 403, origin
    status, _, _ = cancel(port, "whatever", headers={"Origin": "http://evil.example"})
    assert status == 403


def test_non_json_content_type_is_415(port):
    status, _, _ = call(port, "POST", "/api/run", body=b'{"step": "forgery"}', headers={"Content-Type": "text/plain"})
    assert status == 415
    status, _, _ = call(port, "POST", "/api/jobs/x/cancel", body=b"{}", headers={"Content-Type": "text/plain"})
    assert status == 415


@pytest.mark.parametrize("host", ["[::1]evil.com", "localhost:evil", "evil.com", "localhost.evil.com:80",
                                  "127.0.0.1:80:80", "[::1", "", "user@localhost"])
def test_malformed_or_foreign_host_is_403(port, host):
    assert call(port, "GET", "/api/state", host=host)[0] == 403
    assert call(port, "POST", "/api/run", body={"step": "forgery"}, host=host)[0] == 403


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST:8765", "127.0.0.1:1", "[::1]:8765", "[::1]"])
def test_local_hosts_are_accepted(port, host):
    assert call(port, "GET", "/api/state", host=host)[0] == 200


def test_gpu_probe_reports_the_last_stderr_line(monkeypatch):
    monkeypatch.setattr(server, "ENV", {"status": "probing"})
    monkeypatch.setattr(server, "PY", sys.executable)
    try:
        import torch  # noqa: F401
        pytest.skip("torch is installed here, so the probe succeeds")
    except ImportError:
        pass
    server.probe_env()
    assert server.ENV["status"] == "error"
    assert server.ENV["error"].endswith("ModuleNotFoundError: No module named 'torch'")
    monkeypatch.setattr(server, "PY", str(DEMO / "no-such-python.exe"))
    server.probe_env()
    assert server.ENV["status"] == "error" and "FileNotFoundError" in server.ENV["error"]


def test_host_and_origin_parsers():
    assert server.host_of("[::1]evil.com") is None and server.host_of("localhost:evil") is None
    assert server.host_of("[::1]:8765") == "::1" and server.host_of("Localhost:5173") == "localhost"
    assert server.origin_allowed("http://localhost:5173") and server.origin_allowed("http://[::1]:3000")
    assert not server.origin_allowed("http://[::1]evil.com") and not server.origin_allowed("http://localhost:evil")


# ---------------------------------------------------------------------------------- job lifecycle (simulate)
def test_cancel_simulated_job_then_run_again(port):
    status, _, job = run(port)
    assert status == 202 and job["cancelled"] is False and job["timed_out"] is False
    status, _, busy = run(port, step="attacks")
    assert status == 409 and busy["job"]["id"] == job["id"]

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

    monkeypatch.setattr(server.SimJob, "_run", boom)
    status, _, job = run(port)
    assert status == 202
    final = wait_done(port, job["id"])
    assert final["code"] == 1 and not final["cancelled"] and not final["timed_out"]
    assert any("RuntimeError: boom" in line for line in final["output"])
    monkeypatch.undo()
    status, _, nxt = run(port)
    assert status == 202


def test_simulated_job_times_out(port, monkeypatch):
    monkeypatch.setitem(server.STEP_INFO["forgery"], "timeout", 0.3)
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
    if (server.SIM_LOGS / "committed_100000.log").exists():
        assert line.endswith("committed_100000.log")
    else:
        assert "committed.log" in line and "no recording for tries=100,000" in line
    cancel(port, job["id"])

    status, _, job = run(port, step="committed", tries=20000)
    detail = wait_for_line(port, job["id"], "[SIMULATED] Replaying contract/fixtures/logs/")
    assert "[SIMULATED] Replaying contract/fixtures/logs/committed.log" in detail["output"]


# ---------------------------------------------------------------------------------- live jobs (real processes)
@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setitem(server.CONFIG, "simulate", False)
    monkeypatch.setattr(server, "RESULTS", tmp_path)      # web_job_log.txt goes here, not demo/results


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:                                   # a killed but not yet reaped process is a zombie: dead
        return "\nState:\tZ" not in Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return True


def test_live_cancel_kills_the_process_tree(port, live, monkeypatch):
    # The grandchild holds the output pipe: unless the whole tree dies, the job could never end.
    code = ("import subprocess, sys, time\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=sys.stdout, stderr=sys.stderr)\n"
            "print('GPID', g.pid, flush=True)\n"
            "time.sleep(30)\n")
    monkeypatch.setitem(server.STEPS, "forgery", [["-c", code]])
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
        assert run(port)[0] == 202                       # not wedged
    finally:
        if _alive(gpid):
            subprocess.run(["taskkill", "/F", "/PID", str(gpid)] if os.name == "nt" else ["kill", "-9", str(gpid)],
                           capture_output=True)


def test_live_job_times_out(port, live, monkeypatch):
    monkeypatch.setitem(server.STEPS, "forgery", [["-c", "import time; print('working', flush=True); time.sleep(30)"]])
    monkeypatch.setitem(server.STEP_INFO["forgery"], "timeout", 1)
    status, _, job = run(port)
    assert status == 202
    final = wait_done(port, job["id"], timeout=15)
    assert final["code"] == -3 and final["timed_out"] is True
    assert any("timed out after 1 s" in line for line in final["output"])


def test_live_job_success_and_failure_codes(port, live, monkeypatch):
    monkeypatch.setitem(server.STEPS, "forgery", [["-c", "print('ok')"], ["-c", "import sys; sys.exit(3)"],
                                                  ["-c", "print('never runs')"]])
    status, _, job = run(port)
    final = wait_done(port, job["id"])
    assert final["code"] == 3 and not final["cancelled"] and not final["timed_out"]
    assert "ok" in final["output"] and "never runs" not in final["output"]


def test_absolute_paths_are_scrubbed_from_output_and_log(port, live, monkeypatch, tmp_path):
    monkeypatch.setitem(server.STEPS, "forgery", [["-c", "import os; print('cwd', os.getcwd())"]])
    status, _, job = run(port)
    final = wait_done(port, job["id"])
    assert final["code"] == 0 and "cwd demo" in final["output"]
    log = (tmp_path / "web_job_log.txt").read_text(encoding="utf-8")
    assert "cwd demo" in log and str(server.ROOT) not in log


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
    monkeypatch.setitem(server.STEPS, "forgery", [["-c", "print('fine')"]])
    status, _, job = run(port)
    assert status == 202 and wait_done(port, job["id"])["code"] == 0
