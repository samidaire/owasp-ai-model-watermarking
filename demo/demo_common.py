"""Dependency-free helpers shared by run_all.py (CLI) and server.py (web UI), so both launch
the demo scripts the same way. Keep this free of torch/ezkl imports."""
import json
import os
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


def write_json(name, obj):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")


def current_commitment():
    """The owner's published SHA-256 seed commitment; every result records it to detect staleness."""
    p = RESULTS / "public_commitment.json"
    return json.loads(p.read_text())["commitment_sha256"] if p.exists() else None
