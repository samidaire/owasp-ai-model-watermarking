"""Local web server for the demo UI (standard library only). Full API: ../UI_INTEGRATION.md

  python server.py                 # serve ../frontend/dist and run demos live at http://127.0.0.1:8765
  python server.py --open          # ... and open the browser
  python server.py --ui PATH       # serve a different static UI build instead (drop-in replacement)
  python server.py --simulate      # UI development without the ML stack: runs replay recorded logs

- Runs only the whitelisted demo steps below, one job at a time, launched exactly like run_all.py
  (same interpreter, cwd, environment and noise filter; see demo_common.py).
- Streams job output to the browser with Server-Sent Events.
- A running job can be cancelled (POST /api/jobs/{id}/cancel) and is killed after its step's timeout.
  Whatever happens inside a job (crash, kill, timeout), it always finishes, so the server never stays busy.
- Binds to 127.0.0.1 only; rejects foreign Host/Origin headers (DNS rebinding / cross-site POSTs);
  CORS is answered only for localhost origins, so a UI dev server on another port can call the API.
- Needs only the Python standard library to serve saved results. Live runs need demo/.venv (torch, ezkl).
"""
import argparse
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from demo_common import RESULTS, ROOT, child_env, current_commitment, is_noise

API_VERSION = 1
DIST = ROOT.parent / "frontend" / "dist"
SIM_LOGS = ROOT.parent / "contract" / "fixtures" / "logs"
PY = sys.executable
DEFAULT_TRIES = 20000
TRIES_ALLOWED = (20000, 100000)
MAX_BODY = 64 * 1024          # request bodies are tiny JSON objects
CANCEL_WAIT = 5.0             # seconds POST .../cancel waits for the job to actually end
CODE_CANCELLED, CODE_TIMED_OUT = -2, -3
# sim_delay scales the replay pauses of --simulate (tests may shorten them)
CONFIG = {"ui": DIST, "simulate": False, "sim_delay": 1.0}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# step -> list of script invocations ("{tries}" is substituted from the request)
STEPS = {
    "evaluate": [["evaluate_owner.py"]],
    "retrain": [["01_train.py"]],
    "attacks": [["02_attacks.py"]],
    "forgery": [["03_forgery.py"]],
    "committed": [["04_committed_seed.py", "--tries", "{tries}"]],
    "zk": [["05_ezkl_spike.py", "--vis", "private", "--who", "owner"],
           ["05_ezkl_spike.py", "--vis", "private", "--who", "thief", "--keep-onnx"],   # 06 needs it, then deletes it
           ["06_vk_crosscheck.py"]],
    "zk_hashed": [["05_ezkl_spike.py", "--vis", "hashed", "--who", "owner"],
                  ["05_ezkl_spike.py", "--vis", "hashed", "--who", "thief"],
                  ["07_commitment_summary.py"]],      # E3 verdict + public-signal checks into the summaries
}
STEPS["all"] = STEPS["evaluate"] + STEPS["attacks"] + STEPS["forgery"] + STEPS["committed"] + STEPS["zk"]

# Step catalogue for UIs (GET /api/steps). "confirm" = ask the user before starting.
STEP_INFO = {
    "evaluate": {"panel": "A", "label": "Re-verify live", "seconds": 5, "confirm": None,
                 "writes": ["train.json"], "description": "Re-checks the saved owner models. Does not retrain."},
    "retrain": {"panel": "A", "label": "Retrain with a new seed", "seconds": 35,
                "confirm": "Creates a NEW owner seed and key. Every other result (B-E) becomes stale and E3's "
                           "precomputed proofs must be re-run (~3 min, ~10 GB temporary disk). Continue?",
                "writes": ["public_commitment.json", "train.json"], "description": "Starts over with a new owner key."},
    "attacks": {"panel": "B", "label": "Run attacks live", "seconds": 10, "confirm": None,
                "writes": ["attacks.json", "attacks.csv", "attacks.png"], "description": "Removal-attack suite."},
    "forgery": {"panel": "C", "label": "Run forgery live", "seconds": 3, "confirm": None,
                "writes": ["forgery.json"], "description": "Counterfeit-key forgery and ZKROWNN relation check."},
    "committed": {"panel": "D", "label": "Run live", "seconds": 3, "confirm": None, "options": {"tries": list(TRIES_ALLOWED)},
                  "writes": ["committed_seed.json", "forgery_search.png"], "description": "Committed-seed defence (D0-D2)."},
    "zk": {"panel": "E", "label": "Run E1 + E2 live", "seconds": 10, "confirm": None,
           "writes": ["ezkl_private_owner/summary.json", "ezkl_private_thief/summary.json", "vk_crosscheck.json"],
           "description": "EZKL proofs without commitment (owner, thief) and the VK cross-check."},
    "zk_hashed": {"panel": "E", "label": "Re-run E3", "seconds": 200,
                  "confirm": "Re-run the Poseidon-committed proofs? ~3 minutes and a ~10 GB temporary proving key per proof.",
                  "writes": ["ezkl_hashed_owner/summary.json", "ezkl_hashed_thief/summary.json"],
                  "description": "EZKL proofs with a Poseidon commitment to the private parameters."},
    "all": {"panel": "*", "label": "Run all live", "seconds": 30, "confirm": None, "writes": [],
            "description": "evaluate, attacks, forgery, committed, zk (E3 stays precomputed)."},
}


def step_timeout(step_id: str, seconds: float) -> int:
    """Generous per-step limit (seconds): a job still running after it is killed (code -3)."""
    return 1800 if step_id == "zk_hashed" else int(max(120, 10 * seconds))


for _id, _info in STEP_INFO.items():
    _info["timeout"] = step_timeout(_id, _info["seconds"])

# Windows' registry can map .js to text/plain, which browsers refuse for module scripts.
CONTENT_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
                 ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
                 ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain; charset=utf-8",
                 ".csv": "text/csv; charset=utf-8", ".map": "application/json", ".webp": "image/webp",
                 ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".wasm": "application/wasm"}

# Children get their own process group on POSIX so the whole tree can be killed at once.
POPEN_GROUP = {} if os.name == "nt" else {"start_new_session": True}


def kill_tree(proc):
    """Kill a child process and everything it started (Windows and POSIX). Never raises."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass


def rel(p) -> str:
    """Path relative to the repo root, for messages (never show absolute user paths)."""
    try:
        return Path(p).resolve().relative_to(ROOT.parent).as_posix()
    except (ValueError, OSError):
        return Path(p).name


class Job:
    """One run of a step: its scripts run one after another, each in a child process."""

    def __init__(self, step, cmds, tries=DEFAULT_TRIES, timeout=None):
        self.id = uuid.uuid4().hex[:12]
        self.step, self.cmds, self.tries, self.timeout = step, cmds, tries, timeout
        self.lines, self.done, self.code = [], False, None
        self.cancelled, self.timed_out = False, False
        self.started, self.ended = time.time(), None
        self.cond = threading.Condition()
        self.stop = threading.Event()      # set by cancel() or by the timeout watchdog
        self.proc = None                   # the child process currently running, if any

    def push(self, line):
        with self.cond:
            self.lines.append(line)
            self.cond.notify_all()

    def info(self):
        return {"id": self.id, "step": self.step, "running": not self.done, "code": self.code,
                "started": self.started, "ended": self.ended, "lines": len(self.lines),
                "cancelled": self.cancelled, "timed_out": self.timed_out}

    def finish(self, code):
        with self.cond:
            self.code, self.done, self.ended = code, True, time.time()
            self.cond.notify_all()

    def wait(self, timeout=None) -> bool:
        """Block until the job has finished (or `timeout` s pass). True if finished."""
        with self.cond:
            return self.cond.wait_for(lambda: self.done, timeout)

    def cancel(self) -> bool:
        """Stop a running job (kills its process tree). False if it had already finished."""
        with self.cond:
            if self.done:
                return False
            if not (self.timed_out or self.stop.is_set()):   # a timeout that already fired wins
                self.cancelled = True
        self.stop.set()
        self.kill()
        return True

    def kill(self):
        proc = self.proc
        if proc is not None and proc.poll() is None:
            kill_tree(proc)

    def _watchdog(self):
        with self.cond:
            if self.cond.wait_for(lambda: self.done, self.timeout) or self.stop.is_set():
                return
            self.timed_out = True
        self.push(f"[server] timed out after {self.timeout:g} s: stopping the job")
        self.stop.set()
        self.kill()

    def run(self):
        """Thread body. Whatever happens (crash, cancel, timeout), the job ends in finish(),
        so one bad run can never leave the server busy."""
        code = 1
        try:
            if self.timeout:
                threading.Thread(target=self._watchdog, daemon=True).start()
            code = self._run()
        except Exception:  # noqa: BLE001 - reported to the UI as console lines
            for line in traceback.format_exc().rstrip().splitlines():
                self.push(line)
            self.push(f"[server] job {self.id} crashed")
            code = 1
        finally:
            self.kill()                    # never leave a child process behind
            if self.cancelled:
                self.push("[server] cancelled")
                code = CODE_CANCELLED
            elif self.timed_out:
                code = CODE_TIMED_OUT
            self.finish(code)

    def _run(self) -> int:
        code = 0
        with open(RESULTS / "web_job_log.txt", "a", encoding="utf-8") as log:
            log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} job {self.id} step={self.step}\n")
            for cmd in self.cmds:
                if self.stop.is_set():
                    break
                self.push(f"$ python {' '.join(cmd)}")
                try:
                    self.proc = subprocess.Popen([PY, "-u", *cmd], cwd=ROOT, stdout=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                                 errors="replace", env=child_env(), **POPEN_GROUP)
                except OSError as e:
                    self.push(f"failed to start: {e}")
                    return 1
                if self.stop.is_set():     # cancelled while the process was starting
                    self.kill()
                with self.proc.stdout:
                    for line in self.proc.stdout:
                        log.write(line)
                        if not is_noise(line):
                            self.push(line.rstrip("\n"))
                code = self.proc.wait()
                if self.stop.is_set():
                    break
                if code != 0:
                    self.push(f"{cmd[0]} failed (exit {code})")
                    break
        return code


def sim_log_for(step: str, tries: int):
    """Recorded log to replay for (step, tries): '<step>_<tries>.log' when the step takes `tries`
    and a recording for that budget exists, else '<step>.log'. Returns (path or None, wanted path)."""
    uses_tries = any("{tries}" in arg for cmd in STEPS[step] for arg in cmd)
    wanted = SIM_LOGS / (f"{step}_{tries}.log" if uses_tries and tries != DEFAULT_TRIES else f"{step}.log")
    for p in (wanted, SIM_LOGS / f"{step}.log"):
        if p.exists():
            return p, wanted
    return None, wanted


class SimJob(Job):
    """--simulate: replays the recorded output of a real run. Executes nothing, writes nothing."""

    def _run(self) -> int:
        log, wanted = sim_log_for(self.step, self.tries)
        self.push(f"[SIMULATED] Replaying recorded output of step '{self.step}'. Nothing is executed; results/ is unchanged.")
        if log is None:
            self.push(f"[SIMULATED] no recorded log at {rel(wanted)}")
            return 1
        note = "" if log == wanted else f" (no recording for tries={self.tries:,}; numbers below are from a {DEFAULT_TRIES:,}-try run)"
        self.push(f"[SIMULATED] Replaying {rel(log)}{note}")
        for line in log.read_text(encoding="utf-8").splitlines():
            self.push(line)
            if self.stop.wait((0.5 if line.startswith("$ python") else 0.025) * CONFIG["sim_delay"]):
                return 1                   # cancelled or timed out; run() sets the final code
        return 0


JOBS = {}
CURRENT = {"job": None}
LOCK = threading.Lock()
ENV = {"status": "probing"}


def probe_env():
    """GPU/torch facts for the header badge, probed in a child process so the server stays light."""
    code = ("import json,sys,torch;d={'python':sys.version.split()[0],'torch':torch.__version__,"
            "'cuda':torch.version.cuda,'gpu':None}\n"
            "if torch.cuda.is_available():\n p=torch.cuda.get_device_properties(0);"
            "d['gpu']=p.name;d['sm']=f'sm_{p.major}{p.minor}';d['vram_gib']=round(p.total_memory/2**30,1)\n"
            "print(json.dumps(d))")
    try:
        out = subprocess.run([PY, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=120, env=child_env())
        lines = (out.stdout or "").strip().splitlines()
        if out.returncode != 0 or not lines:
            err = (out.stderr or "").strip().splitlines()
            raise RuntimeError(err[-1].strip() if err else f"probe exited with code {out.returncode}")
        facts = json.loads(lines[-1])
        ENV.clear()
        ENV.update(facts)
        ENV["status"] = "ok"
    except Exception as e:  # noqa: BLE001 - surfaced in the UI, never fatal (e.g. no torch installed)
        ENV.clear()
        ENV.update({"status": "error", "error": f"torch not available to {rel(PY)}: {e.__class__.__name__}: {e}"})


def read_json(p: Path):
    """A result file, or None if it is missing, partial or malformed (never raises)."""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - one bad file must not break /api/state
        return None


def state():
    job = CURRENT["job"]
    return {
        "api_version": API_VERSION,
        "mode": "simulate" if CONFIG["simulate"] else "live",
        "env": ENV,
        "commitment": current_commitment(RESULTS),
        "results": {
            "train": read_json(RESULTS / "train.json"),
            "attacks": read_json(RESULTS / "attacks.json"),
            "forgery": read_json(RESULTS / "forgery.json"),
            "committed_seed": read_json(RESULTS / "committed_seed.json"),
            "vk_crosscheck": read_json(RESULTS / "vk_crosscheck.json"),
            "ezkl": {f"{v}_{w}": read_json(RESULTS / f"ezkl_{v}_{w}" / "summary.json")
                     for v in ("private", "hashed") for w in ("owner", "thief")},
        },
        "job": job.info() if job else None,
    }


_HOST_RE = re.compile(r"(?:\[(?P<v6>[0-9A-Fa-f:.]+)\]|(?P<name>[A-Za-z0-9.-]+))(?::(?P<port>[0-9]{1,5}))?")


def host_of(value: str):
    """'127.0.0.1:8765' -> '127.0.0.1', '[::1]:8765' -> '::1'. None if malformed,
    e.g. '[::1]evil.com' or 'localhost:evil' (the port must be digits)."""
    m = _HOST_RE.fullmatch(value or "")
    return (m.group("v6") or m.group("name")).lower() if m else None


def origin_allowed(origin: str) -> bool:
    try:
        u = urlparse(origin)
    except ValueError:                  # e.g. 'http://[::1]evil.com'
        return False
    return u.scheme in ("http", "https") and host_of(u.netloc) in LOCAL_HOSTS


class Handler(BaseHTTPRequestHandler):
    server_version = "WatermarkDemo/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet except for runs
        pass

    # ---------------------------------------------------------------- guards & CORS
    def host_ok(self) -> bool:
        hosts = self.headers.get_all("Host") or []
        if not hosts:
            return True                 # HTTP/1.0 client without a Host header
        return len(hosts) == 1 and host_of(hosts[0]) in LOCAL_HOSTS   # blocks DNS-rebinding hostnames

    def cors(self):
        origin = self.headers.get("Origin")
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    # ---------------------------------------------------------------- helpers
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, cache=None):
        data = path.read_bytes()
        ctype = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache or ("no-cache" if path.suffix == ".html" else "max-age=3600"))
        self.cors()
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def safe_join(base: Path, rel_path: str):
        try:
            p = (base / rel_path.lstrip("/")).resolve()
            return p if p.is_file() and base.resolve() in p.parents else None
        except (OSError, ValueError):   # e.g. invalid characters or an embedded NUL on Windows
            return None

    def read_body(self):
        """Read the (small) request body. Returns (bytes, None) or (None, (status, message))."""
        raw_len = self.headers.get("Content-Length")
        try:
            n = int(raw_len) if raw_len else 0
        except ValueError:
            return None, (400, "bad Content-Length")
        if n < 0:
            return None, (400, "bad Content-Length")
        if n > MAX_BODY:
            return None, (413, "request body too large")
        return (self.rfile.read(n) if n else b""), None

    @staticmethod
    def parse_object(raw: bytes):
        """JSON object from a request body ({} if empty). Returns (dict, None) or (None, message)."""
        try:
            body = json.loads(raw) if raw.strip() else {}
        except ValueError:              # includes invalid UTF-8
            return None, "bad json"
        if not isinstance(body, dict):
            return None, "request body must be a JSON object"
        return body, None

    def internal_error(self):
        traceback.print_exc()
        try:
            self.send_json({"error": "internal server error"}, 500)
        except Exception:  # noqa: BLE001 - the response may already be half-sent
            pass

    # ---------------------------------------------------------------- routes
    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if not self.host_ok() or not origin or not origin_allowed(origin):
            return self.send_json({"error": "origin not allowed"}, 403)
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Last-Event-ID")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        try:
            self.route_get()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001 - answer 500 instead of dropping the connection
            self.internal_error()

    def route_get(self):
        if not self.host_ok():
            return self.send_json({"error": "host not allowed"}, 403)
        path = urlparse(self.path).path
        if path == "/api/state":
            return self.send_json(state())
        if path == "/api/steps":
            return self.send_json({"api_version": API_VERSION, "mode": state()["mode"],
                                   "steps": [{"id": k, **v} for k, v in STEP_INFO.items()]})
        if path.startswith("/api/jobs/"):
            parts = path.split("/")
            job = JOBS.get(parts[3]) if len(parts) > 3 else None
            if not job:
                return self.send_json({"error": "unknown job"}, 404)
            tail = parts[4:]
            if tail in ([], [""]):
                return self.send_json({**job.info(), "output": job.lines})
            if tail == ["stream"]:
                return self.stream(job)
            return self.send_json({"error": "not found"}, 404)
        if path.startswith("/results/"):
            f = self.safe_join(RESULTS, path[len("/results/"):])
            if f and f.suffix in (".png", ".csv", ".json", ".txt"):
                return self.send_file(f, cache="no-cache")      # re-runs must show fresh files
            return self.send_json({"error": "not found"}, 404)
        if path.startswith("/api/"):
            return self.send_json({"error": "not found"}, 404)
        ui = CONFIG["ui"]
        if not (ui / "index.html").exists():
            return self.send_json({"error": f"no UI build at {rel(ui)} (cd frontend && npm run build, or pass --ui)"}, 503)
        f = self.safe_join(ui, path) if path != "/" else None
        return self.send_file(f or ui / "index.html")     # unknown paths -> index.html (SPA routing)

    def do_POST(self):
        try:
            self.route_post()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001 - answer 500 instead of dropping the connection
            self.internal_error()

    def route_post(self):
        path = urlparse(self.path).path
        parts = path.split("/")
        cancel_id = parts[3] if len(parts) == 5 and parts[1:3] == ["api", "jobs"] and parts[4] == "cancel" else None
        if path != "/api/run" and cancel_id is None:
            return self.send_json({"error": "not found"}, 404)
        raw, err = self.read_body()     # read first, so error replies never reset the connection
        origin = self.headers.get("Origin")
        if not self.host_ok() or (origin is not None and not origin_allowed(origin)):
            return self.send_json({"error": "origin not allowed"}, 403)            # cross-site request
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            return self.send_json({"error": "Content-Type must be application/json"}, 415)
        if err:
            return self.send_json({"error": err[1]}, err[0])
        body, msg = self.parse_object(raw)
        if msg:
            return self.send_json({"error": msg}, 400)
        if cancel_id is not None:
            return self.cancel(cancel_id)
        return self.run_step(body)

    def run_step(self, body):
        step = body.get("step")
        if not isinstance(step, str) or step not in STEPS:
            return self.send_json({"error": f"unknown step {step!r}"}, 400)
        try:
            tries = int(body.get("tries", DEFAULT_TRIES))
        except (TypeError, ValueError):
            tries = -1
        if tries not in TRIES_ALLOWED:
            return self.send_json({"error": f"tries must be one of {TRIES_ALLOWED}"}, 400)
        with LOCK:
            cur = CURRENT["job"]
            if cur and not cur.done:
                return self.send_json({"error": "another demo is running", "job": cur.info()}, 409)
            cmds = [[c.replace("{tries}", str(tries)) for c in cmd] for cmd in STEPS[step]]
            job = (SimJob if CONFIG["simulate"] else Job)(step, cmds, tries=tries, timeout=STEP_INFO[step]["timeout"])
            JOBS[job.id] = job
            CURRENT["job"] = job
        print(f"[{time.strftime('%H:%M:%S')}] {'SIMULATE ' if CONFIG['simulate'] else ''}run {step} (job {job.id})", flush=True)
        threading.Thread(target=job.run, daemon=True).start()
        return self.send_json(job.info(), 202)

    def cancel(self, job_id):
        job = JOBS.get(job_id)
        if not job:
            return self.send_json({"error": "unknown job"}, 404)
        if not job.cancel():
            return self.send_json({"error": "job not running", "job": job.info()}, 409)
        print(f"[{time.strftime('%H:%M:%S')}] cancel {job.step} (job {job.id})", flush=True)
        job.wait(CANCEL_WAIT)           # usually ends well within a second; the SSE "done" event follows
        return self.send_json(job.info(), 202)

    def stream(self, job: Job):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.cors()
        self.end_headers()
        # Resume after a reconnect: the browser sends back the last line index it received.
        try:
            sent = max(0, int(self.headers.get("Last-Event-ID", "-1")) + 1)
        except ValueError:
            sent = 0
        try:
            while True:
                with job.cond:
                    if sent >= len(job.lines) and not job.done:
                        job.cond.wait(timeout=10)
                    new, done = job.lines[sent:], job.done
                for i, line in enumerate(new, start=sent):
                    self.wfile.write(f"id: {i}\ndata: {json.dumps(line)}\n\n".encode())
                sent += len(new)
                if not new and not done:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                if done and sent >= len(job.lines):
                    self.wfile.write(f"event: done\ndata: {json.dumps(job.info())}\n\n".encode())
                    self.wfile.flush()
                    return
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return  # tab closed; the job keeps running
        finally:
            self.close_connection = True   # the body has no length: end it by closing (as documented)


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    # HTTPServer sets SO_REUSEADDR, which on Windows lets a SECOND server bind the same port
    # (both "succeed"). Off, so a second launch fails fast and just opens the running UI.
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            super().handle_error(request, client_address)   # real errors still print


def make_server(port=8765, simulate=False, ui=None) -> QuietServer:
    """Configure and bind the server (127.0.0.1 only; port 0 = any free port) without serving yet.
    Raises OSError if the port is taken. Used by main() and by the tests."""
    CONFIG["ui"], CONFIG["simulate"] = Path(ui or DIST).resolve(), bool(simulate)
    return QuietServer(("127.0.0.1", port), Handler)


def stop_current_job(wait=CANCEL_WAIT):
    """Cancel the running job, if any (server shutdown), so no demo process is left behind."""
    job = CURRENT["job"]
    if job and job.cancel():
        job.wait(wait)


def main():
    ap = argparse.ArgumentParser(description="Watermark demo UI server. API reference: ../UI_INTEGRATION.md")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the browser")
    ap.add_argument("--ui", type=Path, default=Path(os.environ.get("DEMO_UI_DIR") or DIST),
                    help="static UI build to serve (default: ../frontend/dist; env DEMO_UI_DIR)")
    ap.add_argument("--simulate", action="store_true",
                    help="replay recorded logs instead of running demos (UI development without torch/ezkl)")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    want_browser = args.open and not os.environ.get("DEMO_NO_BROWSER")   # env switch lets the launcher be tested headless
    try:
        httpd = make_server(args.port, simulate=args.simulate, ui=args.ui)
    except OSError:
        print(f"Port {args.port} is already in use: the demo UI is probably already running at {url}", flush=True)
        if want_browser:
            webbrowser.open(url)
        return
    threading.Thread(target=probe_env, daemon=True).start()
    print(f"Watermark demo UI: {url}   (Ctrl+C to stop)", flush=True)
    if args.simulate:
        print("  *** SIMULATE MODE: runs replay recorded logs; nothing is executed and results/ is not modified ***",
              flush=True)
    if CONFIG["ui"] != DIST.resolve():
        print(f"  serving UI from {rel(CONFIG['ui'])}", flush=True)
    if not (CONFIG["ui"] / "index.html").exists():
        print(f"  note: no index.html in {rel(CONFIG['ui'])} (cd frontend && npm run build)", flush=True)
    if want_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_current_job()
        httpd.server_close()


if __name__ == "__main__":
    main()
