"""The "Model under test" API: GET /api/models, the model_test step and its saved results (simulate mode)."""
import http.client
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
sys.path.insert(0, str(DEMO))
_spec = importlib.util.spec_from_file_location("demo_server_models", DEMO / "server.py")
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)
import model_catalogue as MC  # noqa: E402


@pytest.fixture(scope="module")
def port():
    server.CONFIG["sim_delay"] = 0.0
    httpd = server.make_server(0, simulate=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    server.stop_current_job()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def no_job_left_running():
    yield
    server.stop_current_job()


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        body = json.dumps(body)
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=body, headers=headers)
        r = conn.getresponse()
        return r.status, json.loads(r.read())
    finally:
        conn.close()


def wait_done(port, job_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        _, job = call(port, "GET", f"/api/jobs/{job_id}")
        if not job["running"]:
            return job
        time.sleep(0.05)
    raise AssertionError("job still running")


def test_catalogue_lists_every_builtin_model_with_a_recording_and_a_saved_result():
    ids = [m["id"] for m in MC.catalogue() if not m["id"].startswith("file:")]
    assert ids == list(MC.BUILTIN)
    for i in ids:
        assert (ROOT / "contract" / "fixtures" / "logs" / f"model_test_{i}.log").exists(), i
        saved = json.loads((DEMO / "results" / "model_tests" / f"{i}.json").read_text(encoding="utf-8"))
        assert saved["model"] == i and saved["verdict"] in {"proven", "no_proof", "rejected", "unreadable"}
    for m in MC.catalogue():
        if m["file"]:
            assert (DEMO / m["file"]).is_file(), m


def test_expected_verdicts_of_the_saved_results():
    v = {i: json.loads((DEMO / "results" / "model_tests" / f"{i}.json").read_text(encoding="utf-8"))["verdict"]
         for i in MC.BUILTIN}
    assert v["watermarked_v2"] == "proven"
    assert {v[i] for i in ("prune65", "prune90", "int8", "finetune", "overwrite")} == {"proven"}
    assert v["permute"] == "no_proof"                     # the known limit of a white-box mark
    assert {v[i] for i in ("watermarked_v1", "clean", "null_0", "null_1", "null_2", "null_3")} == {"no_proof"}


def test_api_models_and_state(port):
    status, body = call(port, "GET", "/api/models")
    assert status == 200 and [m["id"] for m in body["models"]][:2] == ["watermarked_v2", "watermarked_v1"]
    _, state = call(port, "GET", "/api/state")
    assert state["results"]["model_tests"]["clean"]["verdict"] == "no_proof"


def test_model_test_needs_a_known_model(port):
    for bad in (None, "", "../../secrets/owner.key", "file:nope.pt", 7):
        body = {"step": "model_test"} if bad is None else {"step": "model_test", "model": bad}
        status, err = call(port, "POST", "/api/run", body)
        assert status == 400 and "unknown model" in err["error"], bad


def test_model_test_replays_that_models_recording(port):
    status, job = call(port, "POST", "/api/run", {"step": "model_test", "model": "permute"})
    assert status == 202 and job["model"] == "permute"
    done = wait_done(port, job["id"])
    assert done["code"] == 0
    out = "\n".join(done["output"])
    assert "MODEL TEST: watermarked_v2 · channels permuted" in out and "NOT PROVEN" in out


def test_safe_name_never_contains_path_characters():
    for i in ("watermarked_v2", "file:../x.pt", "file:a:b.onnx"):
        name = MC.safe_name(i)
        assert all(c.isalnum() or c == "_" for c in name), name


def test_a_users_file_is_listed_but_not_replayed_in_simulate_mode(port):
    MC.USER_DIR.mkdir(exist_ok=True)
    f = MC.USER_DIR / "pytest_dropped_model.pt"
    f.write_bytes(b"not really a model")
    try:
        _, body = call(port, "GET", "/api/models")
        assert "file:pytest_dropped_model.pt" in [m["id"] for m in body["models"]]
        status, job = call(port, "POST", "/api/run", {"step": "model_test", "model": "file:pytest_dropped_model.pt"})
        assert status == 202
        done = wait_done(port, job["id"])
        assert done["code"] == 1 and any("no recording" in line for line in done["output"])
    finally:
        f.unlink()
