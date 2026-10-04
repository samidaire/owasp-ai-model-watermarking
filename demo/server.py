"""Local web server for the demo UI (standard library only). Full API: ../UI_INTEGRATION.md

  python server.py                 # serve ../frontend/dist and run demos live at http://127.0.0.1:8765
  python server.py --open          # ... and open the browser
  python server.py --ui PATH       # serve a different static UI build instead (drop-in replacement)
  python server.py --simulate      # UI development without the ML stack: runs replay recorded logs

- Runs only the whitelisted demo steps below, one job at a time, launched exactly like run_all.py
  (same interpreter, cwd, environment and noise filter; see demo_common.py).
- Streams job output to the browser with Server-Sent Events.
- Binds to 127.0.0.1 only; rejects foreign Host/Origin headers (DNS rebinding / cross-site POSTs);
  CORS is answered only for localhost origins, so a UI dev server on another port can call the API.
- Needs only the Python standard library to serve saved results. Live runs need demo/.venv (torch, ezkl).
"""
import argparse
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
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
TRIES_ALLOWED = (20000, 100000)
CONFIG = {"ui": DIST, "simulate": False}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# step -> list of script invocations ("{tries}" is substituted from the request)
STEPS = {
    "evaluate": [["evaluate_owner.py"]],
    "retrain": [["01_train.py"]],
    "attacks": [["02_attacks.py"]],
    "forgery": [["03_forgery.py"]],
    "committed": [["04_committed_seed.py", "--tries", "{tries}"]],
    "zk": [["05_ezkl_spike.py", "--vis", "private", "--who", "owner"],
           ["05_ezkl_spike.py", "--vis", "private", "--who", "thief"],
           ["06_vk_crosscheck.py"]],
    "zk_hashed": [["05_ezkl_spike.py", "--vis", "hashed", "--who", "owner"],
                  ["05_ezkl_spike.py", "--vis", "hashed", "--who", "thief"]],
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

# Windows' registry can map .js to text/plain, which browsers refuse for module scripts.
CONTENT_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
                 ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
                 ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain; charset=utf-8",
                 ".csv": "text/csv; charset=utf-8", ".map": "application/json", ".webp": "image/webp",
                 ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".wasm": "application/wasm"}


class Job:
    def __init__(self, step, cmds):
        self.id = uuid.uuid4().hex[:12]
        self.step, self.cmds = step, cmds
        self.lines, self.done, self.code = [], False, None
        self.started, self.ended = time.time(), None
        self.cond = threading.Condition()

    def push(self, line):
        with self.cond:
            self.lines.append(line)
            self.cond.notify_all()

    def info(self):
        return {"id": self.id, "step": self.step, "running": not self.done, "code": self.code,
                "started": self.started, "ended": self.ended, "lines": len(self.lines)}

    def finish(self, code):
        with self.cond:
            self.code, self.done, self.ended = code, True, time.time()
            self.cond.notify_all()

    def run(self):
        code = 0
        with open(RESULTS / "web_job_log.txt", "a", encoding="utf-8") as log:
            log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} job {self.id} step={self.step}\n")
            for cmd in self.cmds:
                self.push(f"$ python {' '.join(cmd)}")
                try:
                    proc = subprocess.Popen([PY, "-u", *cmd], cwd=ROOT, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                            errors="replace", env=child_env())
                except OSError as e:
                    self.push(f"failed to start: {e}")
                    code = 1
                    break
                for line in proc.stdout:
                    log.write(line)
                    if not is_noise(line):
                        self.push(line.rstrip("\n"))
                code = proc.wait()
                if code != 0:
                    self.push(f"{cmd[0]} failed (exit {code})")
                    break
        self.finish(code)


class SimJob(Job):
    """--simulate: replays the recorded output of a real run. Executes nothing, writes nothing."""

    def run(self):
        log = SIM_LOGS / f"{self.step}.log"
        self.push(f"[SIMULATED] Replaying recorded output of step '{self.step}'. Nothing is executed; results/ is unchanged.")
        if not log.exists():
            self.push(f"[SIMULATED] no recorded log at {log}")
            return self.finish(1)
        for line in log.read_text(encoding="utf-8").splitlines():
            self.push(line)
            time.sleep(0.5 if line.startswith("$ python") else 0.025)
        self.finish(0)


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
        out = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=120, env=child_env())
        ENV.clear()
        ENV.update(json.loads(out.stdout.strip().splitlines()[-1]))
        ENV["status"] = "ok"
    except Exception as e:  # noqa: BLE001 - surfaced in the UI, never fatal (e.g. no torch installed)
        ENV.clear()
        ENV.update({"status": "error", "error": f"torch not available to {PY}: {e.__class__.__name__}"})


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state():
    job = CURRENT["job"]
    return {
        "api_version": API_VERSION,
        "mode": "simulate" if CONFIG["simulate"] else "live",
        "env": ENV,
        "commitment": current_commitment(),
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


def host_of(value: str) -> str:
    """'127.0.0.1:8765' -> '127.0.0.1', '[::1]:8765' -> '::1'."""
    if value.startswith("["):
        return value[1:value.find("]")]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def origin_allowed(origin: str) -> bool:
    u = urlparse(origin)
    return u.scheme in ("http", "https") and (u.hostname or "") in LOCAL_HOSTS


class Handler(BaseHTTPRequestHandler):
    server_version = "WatermarkDemo/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet except for runs
        pass

    # ---------------------------------------------------------------- guards & CORS
    def host_ok(self) -> bool:
        h = self.headers.get("Host")
        return h is None or host_of(h) in LOCAL_HOSTS        # blocks DNS-rebinding hostnames

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

    def send_file(self, path: Path):
        data = path.read_bytes()
        ctype = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if path.suffix == ".html" else "max-age=3600")
        self.cors()
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def safe_join(base: Path, rel: str):
        p = (base / rel.lstrip("/")).resolve()
        return p if p.is_file() and base.resolve() in p.parents else None

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
        if not self.host_ok():
            return self.send_json({"error": "host not allowed"}, 403)
        path = urlparse(self.path).path
        try:
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
                if len(parts) > 4 and parts[4] == "stream":
                    return self.stream(job)
                return self.send_json({**job.info(), "output": job.lines})
            if path.startswith("/results/"):
                f = self.safe_join(RESULTS, path[len("/results/"):])
                if f and f.suffix in (".png", ".csv", ".json", ".txt"):
                    return self.send_file(f)
                return self.send_json({"error": "not found"}, 404)
            if path.startswith("/api/"):
                return self.send_json({"error": "not found"}, 404)
            ui = CONFIG["ui"]
            if not (ui / "index.html").exists():
                return self.send_json({"error": f"no UI build at {ui} (cd frontend && npm run build, or pass --ui)"}, 503)
            f = self.safe_join(ui, path) if path != "/" else None
            return self.send_file(f or ui / "index.html")     # unknown paths -> index.html (SPA routing)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            return self.send_json({"error": "not found"}, 404)
        origin = self.headers.get("Origin")
        if not self.host_ok() or (origin is not None and not origin_allowed(origin)):
            return self.send_json({"error": "origin not allowed"}, 403)            # cross-site request
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            return self.send_json({"error": "Content-Type must be application/json"}, 415)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        except ValueError:
            return self.send_json({"error": "bad json"}, 400)
        step = body.get("step")
        if step not in STEPS:
            return self.send_json({"error": f"unknown step {step!r}"}, 400)
        try:
            tries = int(body.get("tries", 20000))
        except (TypeError, ValueError):
            tries = -1
        if tries not in TRIES_ALLOWED:
            return self.send_json({"error": f"tries must be one of {TRIES_ALLOWED}"}, 400)
        with LOCK:
            cur = CURRENT["job"]
            if cur and not cur.done:
                return self.send_json({"error": "another demo is running", "job": cur.info()}, 409)
            cmds = [[c.replace("{tries}", str(tries)) for c in cmd] for cmd in STEPS[step]]
            job = (SimJob if CONFIG["simulate"] else Job)(step, cmds)
            JOBS[job.id] = job
            CURRENT["job"] = job
        print(f"[{time.strftime('%H:%M:%S')}] {'SIMULATE ' if CONFIG['simulate'] else ''}run {step} (job {job.id})", flush=True)
        threading.Thread(target=job.run, daemon=True).start()
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


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    # HTTPServer sets SO_REUSEADDR, which on Windows lets a SECOND server bind the same port
    # (both "succeed"). Off, so a second launch fails fast and just opens the running UI.
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            super().handle_error(request, client_address)   # real errors still print


def main():
    ap = argparse.ArgumentParser(description="Watermark demo UI server. API reference: ../UI_INTEGRATION.md")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the browser")
    ap.add_argument("--ui", type=Path, default=Path(os.environ.get("DEMO_UI_DIR") or DIST),
                    help="static UI build to serve (default: ../frontend/dist; env DEMO_UI_DIR)")
    ap.add_argument("--simulate", action="store_true",
                    help="replay recorded logs instead of running demos (UI development without torch/ezkl)")
    args = ap.parse_args()
    CONFIG["ui"], CONFIG["simulate"] = args.ui.resolve(), args.simulate
    url = f"http://127.0.0.1:{args.port}"
    want_browser = args.open and not os.environ.get("DEMO_NO_BROWSER")   # env switch lets the launcher be tested headless
    try:
        httpd = QuietServer(("127.0.0.1", args.port), Handler)
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
        print(f"  serving UI from {CONFIG['ui']}", flush=True)
    if not (CONFIG["ui"] / "index.html").exists():
        print(f"  note: no index.html in {CONFIG['ui']} (cd frontend && npm run build)", flush=True)
    if want_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
