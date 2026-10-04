"""Dependency-free helpers shared by run_all.py (CLI) and server.py (web UI), so both launch
the demo scripts the same way. Keep this free of torch/ezkl imports."""
import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
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


# ---------------------------------------------------------------- atomic result writes
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
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:   # Windows: the target is briefly open in a reader; retry
                if attempt == 19:
                    raise
                time.sleep(0.05)
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
