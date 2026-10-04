"""Shared test setup. These tests need only pytest + numpy (no torch, ezkl or GPU)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "demo"

# demo/ scripts import each other as top-level modules (demo_common, d2_math, zk_checks, ...)
if str(DEMO) not in sys.path:
    sys.path.insert(0, str(DEMO))


def pytest_configure(config):
    # CI runs `pytest -m "not ml and not zk"`; register the markers so they are not unknown.
    config.addinivalue_line("markers", "ml: needs torch / the ML stack")
    config.addinivalue_line("markers", "zk: needs ezkl / circom")
