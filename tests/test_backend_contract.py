"""API-02 contract tests: /api/state, /api/steps and /api/jobs/{id} have the shapes of contract/fixtures
(real responses captured from demo/server.py), so the current UI works unchanged against FastAPI."""
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from backend.app import legacy  # noqa: E402
from backend.testing import app_client  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "contract" / "fixtures"


def kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    return type(v).__name__


def assert_shape(expected, got, path="$"):
    """Every key of the fixture exists in the response with a compatible type (null = result not present)."""
    if expected is None or got is None:
        return
    assert kind(expected) == kind(got), f"{path}: fixture has {kind(expected)}, server has {kind(got)}"
    if isinstance(expected, dict):
        missing = set(expected) - set(got)
        assert not missing, f"{path}: missing keys {sorted(missing)}"
        for k in expected:
            assert_shape(expected[k], got[k], f"{path}.{k}")
    elif isinstance(expected, list) and expected and got:
        assert_shape(expected[0], got[0], f"{path}[0]")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with app_client(tmp_path_factory.mktemp("contract")) as (app, client):
        yield app, client


def test_state_matches_the_fixture(env):
    _, c = env
    fixture = json.loads((FIX / "state.json").read_text(encoding="utf-8"))
    state = c.get("/api/state").json()
    assert set(state) == set(fixture)
    assert state["api_version"] == fixture["api_version"] == 1
    assert state["mode"] in ("live", "simulate") and state["env"]["status"] in ("probing", "ok", "error")
    assert set(state["results"]) >= set(fixture["results"])
    assert set(state["results"]["ezkl"]) == set(fixture["results"]["ezkl"])
    assert_shape(fixture["results"], state["results"], "$.results")
    assert state["job"] is None or set(state["job"]) >= set(fixture["job"])


def test_steps_match_the_fixture(env):
    _, c = env
    fixture = json.loads((FIX / "steps.json").read_text(encoding="utf-8"))
    body = c.get("/api/steps").json()
    assert body["api_version"] == 1 and set(body) == set(fixture)
    got = {s["id"]: s for s in body["steps"]}
    for step in fixture["steps"]:
        mine = got[step["id"]]
        for k, v in step.items():
            assert mine[k] == v, (step["id"], k)
        assert mine["timeout"] == legacy.STEP_INFO[step["id"]]["timeout"]
    assert set(got) == set(legacy.STEPS)                   # newer steps (e.g. protocol_v2) are additions


def test_job_detail_matches_the_fixture(env):
    _, c = env
    fixture = json.loads((FIX / "job.json").read_text(encoding="utf-8"))
    r = c.post("/api/run", json={"step": "forgery"})
    assert r.status_code == 202
    assert set(r.json()) >= set(fixture) - {"output"}
    job_id = r.json()["id"]
    c.post(f"/api/jobs/{job_id}/cancel", json={})
    for _ in range(100):
        detail = c.get(f"/api/jobs/{job_id}").json()
        if not detail["running"]:
            break
        time.sleep(0.05)
    assert_shape(fixture, detail)
    assert set(detail) == set(fixture) | {"cancelled", "timed_out"}
    assert isinstance(detail["output"], list) and all(isinstance(x, str) for x in detail["output"])


def test_simulate_logs_exist_for_every_step():
    for step in legacy.STEPS:
        assert (FIX / "logs" / f"{step}.log").exists(), step
