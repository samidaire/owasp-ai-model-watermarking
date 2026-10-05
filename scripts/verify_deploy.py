"""Check that a deployment works, end to end. Standard library only; prints PASS/FAIL per check.

    python scripts/verify_deploy.py               # live deployment: toolchain, tests, and a real proof via the server
    python scripts/verify_deploy.py --simulate    # replay-only deployment (nothing installed): app + recorded runs
    python scripts/verify_deploy.py --json        # also print a JSON summary (for scripts and agents)

Exit code 0 when every check passed, 1 otherwise. Leaves the working tree as it found it: the smoke test's
model result is restored afterwards, and the server it starts is stopped. See DEPLOY.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IS_WIN = os.name == "nt"
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
CIRCUIT = "ownership_T64_M288_E8_W24"
RESULTS: list[dict] = []


def report(name: str, ok: bool, detail: str = "", fix: str = "") -> bool:
    RESULTS.append({"check": name, "ok": ok, "detail": detail, "fix": "" if ok else fix})
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
    if not ok and fix:
        print(f"      fix: {fix}", flush=True)
    return ok


def out(cmd: list, timeout: int = 120, cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=cwd)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- static checks
def check_static(simulate: bool) -> None:
    report("python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0],
           "install Python 3.10+ from python.org (tick 'Add python.exe to PATH')")
    dist = ROOT / "frontend" / "dist" / "index.html"
    if report("web app build present", dist.exists(), "frontend/dist/index.html",
              "the zip ships it; from git: cd frontend && npm ci && npm run build"):
        code, text = out([sys.executable, ROOT / "scripts" / "check_offline_build.py", ROOT / "frontend" / "dist"])
        report("web app loads nothing from the internet", code == 0, text.splitlines()[-1] if text else "",
               "rebuild the app: cd frontend && npm ci && npm run build")
    report("saved results present", (ROOT / "demo" / "results" / "protocol_v2.json").exists(), "demo/results/",
           "unzip the package again: demo/results/ is part of it")
    if simulate:
        return

    if not report("project venv (.venv)", VENV_PY.exists(), str(VENV_PY.relative_to(ROOT)),
                  "run the setup: .\\setup.ps1 --demo (Windows) or ./setup.sh --demo"):
        return
    code, text = out([VENV_PY, "-c", "import torch, numpy, sigil, onnx; print(torch.__version__, "
                      "'cuda' if torch.cuda.is_available() else 'cpu', sigil.__version__)"], timeout=300)
    report("python packages (torch, numpy, onnx, sigil)", code == 0, text.splitlines()[-1] if text else "",
           "re-run the setup; it installs everything into .venv")
    code, text = out(["node", "--version"])
    ver = tuple(int(x) for x in text.lstrip("v").split(".")[:2]) if code == 0 and text.startswith("v") else (0, 0)
    report("node >= 20.19", ver >= (20, 19), text or "not found", "install Node.js 20.19+ (LTS) from nodejs.org, then re-run the setup")
    snark = ROOT / "circuits" / "node_modules" / "snarkjs" / "package.json"
    report("snarkjs installed", snark.exists(), json.loads(snark.read_text())["version"] if snark.exists() else "missing",
           "re-run the setup (it runs npm ci in circuits/)")
    circom = ROOT / "tools" / "bin" / ("circom.exe" if IS_WIN else "circom")
    code, text = out([circom, "--version"]) if circom.exists() else (1, "missing")
    report("circom compiler", code == 0, text.splitlines()[-1] if text else "",
           "re-run the setup (it downloads circom 2.2.3 from github.com/iden3/circom); allow it in the antivirus")
    zkey = ROOT / "circuits" / "build" / f"{CIRCUIT}.zkey"
    wasm = ROOT / "circuits" / "build" / f"{CIRCUIT}_js" / f"{CIRCUIT}.wasm"
    want = json.loads((ROOT / "circuits" / "keys" / f"{CIRCUIT}.setup.json").read_text())["zkey_sha256"]
    report("proving key matches its setup transcript", zkey.exists() and sha256(zkey) == want,
           zkey.name if zkey.exists() else "missing",
           "re-run the setup (it installs dist/sigil-proving-keys-t64.zip), or: .venv python -m sigil.cli zk-setup --bits 64")
    report("circuit witness generator", wasm.exists(), wasm.name, "same as the proving key")
    data = ROOT / "demo" / "data"
    report("MNIST data", all((data / f).exists() for f in ("train-images-idx3-ubyte.gz", "t10k-images-idx3-ubyte.gz")),
           "demo/data/", "unzip the package again: demo/data/ is part of it")
    code, text = out([VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", ROOT / "tests"], timeout=600, cwd=ROOT)
    report("server and protocol tests", code == 0, text.splitlines()[-1] if text else "",
           "read the failing test's output: python -m pytest -q tests")


# ---------------------------------------------------------------- the running app
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def api(port: int, path: str, body: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_step(port: int, body: dict, timeout: int) -> dict:
    job = api(port, "/api/run", body)
    end = time.time() + timeout
    while time.time() < end:
        j = api(port, f"/api/jobs/{job['id']}")
        if not j["running"]:
            return j
        time.sleep(0.5)
    raise TimeoutError(f"{body['step']} still running after {timeout} s")


def check_server(simulate: bool) -> None:
    py = sys.executable if simulate or not VENV_PY.exists() else VENV_PY
    port = free_port()
    log = Path(tempfile.mkdtemp(prefix="sigil_verify_")) / "server.log"
    cmd = [str(py), str(ROOT / "demo" / "server.py"), "--port", str(port)] + (["--simulate"] if simulate else [])
    saved = ROOT / "demo" / "results" / "model_tests" / "watermarked_v2.json"
    backup = saved.read_bytes() if saved.exists() else None
    with open(log, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(cmd, cwd=ROOT / "demo", stdout=logf, stderr=subprocess.STDOUT)
        try:
            state = None
            for _ in range(60):
                try:
                    state = api(port, "/api/state", timeout=5)
                    break
                except (urllib.error.URLError, ConnectionError, OSError):
                    time.sleep(0.5)
            if not report("app server starts", state is not None, f"http://127.0.0.1:{port}",
                          "port blocked or Python error: see the server log printed below"):
                return
            report("app mode", state["mode"] == ("simulate" if simulate else "live"), state["mode"])
            if not simulate:
                for _ in range(240):
                    if state["env"].get("status") != "probing":
                        break
                    time.sleep(0.5)
                    state = api(port, "/api/state")
                env = state["env"]
                report("server sees PyTorch", env.get("status") == "ok",
                       env.get("gpu") or ("CPU only, torch " + str(env.get("torch"))) if env.get("status") == "ok" else env.get("error", ""),
                       "the server must run with .venv's Python: use Start-Demo-UI.cmd or .venv python demo/server.py")
            steps = api(port, "/api/steps")["steps"]
            models = api(port, "/api/models")["models"]
            report("step catalogue", {"protocol_v2", "model_test", "verify_honest"} <= {s["id"] for s in steps}, f"{len(steps)} steps")
            report("model catalogue", len(models) >= 13, f"{len(models)} models")
            j = run_step(port, {"step": "verify_honest"}, 120)
            text = "\n".join(j.get("output", []))
            report("verify the saved proof" + (" (replayed recording)" if simulate else " (SnarkJS)"),
                   j["code"] == 0 and "VERDICT: ACCEPTED" in text,
                   f"exit {j['code']}", "see the server log; usually node/snarkjs: re-run the setup")
            j = run_step(port, {"step": "model_test", "model": "watermarked_v2"}, 420)
            text = "\n".join(j.get("output", []))
            report("prove ownership of a model" + (" (replayed recording)" if simulate else " (torch + circom + Groth16)"),
                   j["code"] == 0 and "OWNERSHIP PROVEN" in text,
                   f"exit {j['code']}", "see the job output in the server log; check torch, circom and the proving key above")
        except Exception as e:  # noqa: BLE001 - reported as a failed check
            report("app smoke test", False, f"{type(e).__name__}: {e}", "see the server log printed below")
        finally:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
            if backup is not None and not simulate:
                saved.write_bytes(backup)          # leave the shipped result as it was
    if not all(r["ok"] for r in RESULTS):
        print("\n--- server log (last 40 lines) ---")
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]))
    shutil.rmtree(log.parent, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--simulate", action="store_true", help="check a replay-only deployment (no .venv needed)")
    ap.add_argument("--skip-server", action="store_true", help="only the static checks and tests")
    ap.add_argument("--json", action="store_true", help="print a JSON summary at the end")
    args = ap.parse_args()
    print(f"Verifying the {'replay-only' if args.simulate else 'live'} deployment in {ROOT}\n")
    check_static(args.simulate)
    if not args.skip_server:
        check_server(args.simulate)
    failed = [r for r in RESULTS if not r["ok"]]
    print("\n" + ("ALL CHECKS PASSED" if not failed else f"{len(failed)} CHECK(S) FAILED: " + ", ".join(r["check"] for r in failed)))
    if args.json:
        print(json.dumps({"ok": not failed, "mode": "simulate" if args.simulate else "live", "checks": RESULTS}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
