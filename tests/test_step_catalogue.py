"""Every runnable step is documented and replayable in simulate mode (incl. demo F, protocol_v2)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))
spec = importlib.util.spec_from_file_location("demo_server_catalogue", ROOT / "demo" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_every_step_has_info_and_a_fixture_log():
    assert set(server.STEPS) == set(server.STEP_INFO)
    for step in server.STEPS:
        info = server.STEP_INFO[step]
        assert info["timeout"] >= info["seconds"]
        assert (ROOT / "contract" / "fixtures" / "logs" / f"{step}.log").exists(), step


def test_protocol_v2_step_runs_demo_f():
    assert server.STEPS["protocol_v2"] == [["08_protocol_v2.py"]]
    assert server.STEP_INFO["protocol_v2"]["panel"] == "F"
    assert "protocol_v2.json" in server.STEP_INFO["protocol_v2"]["writes"]
