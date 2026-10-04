"""Dependency-free helpers shared by run_all.py (CLI) and server.py (web UI), so both launch
the demo scripts the same way. Keep this free of torch/ezkl imports."""
import json
import os
import re
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
RESULTS = ROOT / "results"

# EZKL/ONNX chatter that is harmless but confusing on screen (still written to logs)
NOISE = ("decomposition error", "forward pass failed", "[torch.onnx]", "W1005", "torchvision is not installed",
         "triton not found", "version conversion", "Setting ONNX exporter", "+----", "| mean_error", "| 0 ",
         "DeprecationWarning", "torch.onnx.export(model", "Numerical Fidelity Report")


def child_env():
    """EZKL panics without HOME (unset in PowerShell/cmd); force UTF-8 so Windows pipes don't choke."""
    return {"HOME": str(Path.home()), **os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def is_noise(line: str) -> bool:
    return any(n in line for n in NOISE)


# ---------------------------------------------------------------- no absolute user paths in logs (FIX-15)
def _prefix_re(path: Path):
    """This checkout's absolute path, either slash style (case-insensitive on Windows), plus a separator."""
    parts = [re.escape(p) for p in re.split(r"[\\/]+", str(path)) if p]
    head = "/" if str(path).startswith("/") else ""
    return re.compile(head + r"[\\/]+".join(parts) + r"[\\/]+", re.IGNORECASE if os.name == "nt" else 0)


_THIS_REPO = _prefix_re(REPO)
# 'C:\Users\x', 'C:/Users/x', '/home/x', '/Users/x', Git Bash '/c/Users/x'
_HOME = r"(?:\b[A-Za-z]:[\\/]|(?<![\w.~])/(?:[A-Za-z]/)?)(?:Users|home|Documents and Settings)[\\/][^\\/\r\n]+"
# Someone else's checkout (e.g. a recorded log): cut everything before its demo/ folder.
_OTHER_REPO = re.compile(_HOME + r"[\\/](?:[^\\/\r\n]+[\\/])*?(?=demo[\\/])", re.IGNORECASE)
# Any other home folder: hide the user name.
_HOME_DIR = re.compile(_HOME + r"(?=[\\/]|$)", re.IGNORECASE)


def scrub_paths(line: str) -> str:
    """Make absolute paths in a log line relative to the repo root ('C:\\Users\\me\\...\\demo\\x.py'
    -> 'demo\\x.py'), and replace any other home folder with '~'. Used for everything logged or
    streamed (run_all.py, server.py), since tracebacks and warnings print absolute paths."""
    line = _THIS_REPO.sub("", line)
    line = _OTHER_REPO.sub("", line)
    return _HOME_DIR.sub("~", line)


# ---------------------------------------------------------------- atomic result writes
def replace_file(src, dst, attempts=20):
    """os.replace(src, dst), retrying briefly: on Windows it fails while a reader has dst open."""
    for attempt in range(attempts):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)


def atomic_write_bytes(path, data: bytes):
    """Write to a temp file in the same directory, then os.replace() it over `path`.
    Readers (the web server, the UI) see either the old file or the new one, never a partial one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        replace_file(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path, text: str):
    atomic_write_bytes(path, text.encode("utf-8"))


def write_json(name, obj):
    """results/<name> (name may contain a subfolder, e.g. 'ezkl_private_owner/summary.json'),
    or an absolute path. Written atomically."""
    p = Path(name)
    atomic_write_text(p if p.is_absolute() else RESULTS / p, json.dumps(obj, indent=2))


def current_commitment(results=None):
    """The owner's published SHA-256 seed commitment; every result records it to detect staleness.
    None if the file is missing, partial or malformed (never raises)."""
    p = Path(results or RESULTS) / "public_commitment.json"
    try:
        c = json.loads(p.read_text(encoding="utf-8")).get("commitment_sha256")
    except Exception:  # noqa: BLE001 - OSError, bad JSON, not an object, ...
        return None
    return c if isinstance(c, str) else None
