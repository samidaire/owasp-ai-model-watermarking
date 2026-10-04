"""Smoke tests for 06_vk_crosscheck.py and 07_commitment_summary.py without torch/ezkl: small
stand-ins replace torch, wm_core and ezkl, and the scripts run on a copy of the saved EZKL results.
They check the wiring of the public-signal checks (FIX-02); the maths is in test_zk_checks.py."""
import json
import runpy
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pytest

import demo_common

REPO = Path(__file__).resolve().parents[1]
DEMO, SAVED = REPO / "demo", REPO / "demo" / "results"
KEEP = ("proof.json", "settings.json", "summary.json", "input.json")


class FakeTensor:
    def __init__(self, a):
        self.a = np.asarray(a, dtype=np.float64)

    def detach(self):
        return self

    def std(self):
        return 1.0                     # the saved input.json vector is already w / std

    def __truediv__(self, other):
        return FakeTensor(self.a / other)

    def flatten(self):
        return FakeTensor(self.a.ravel())

    def tolist(self):
        return self.a.tolist()


@pytest.fixture
def results(tmp_path, monkeypatch):
    res = tmp_path / "results"
    for run in ("private_owner", "private_thief", "hashed_owner", "hashed_thief"):
        (res / f"ezkl_{run}").mkdir(parents=True)
        for name in KEEP:
            shutil.copy(SAVED / f"ezkl_{run}" / name, res / f"ezkl_{run}" / name)
    shutil.copy(SAVED / "public_commitment.json", res / "public_commitment.json")
    w = json.loads((SAVED / "ezkl_private_owner" / "input.json").read_text())["input_data"][0]

    torch = types.ModuleType("torch")
    torch.device = lambda name: name
    wm_core = types.ModuleType("wm_core")
    wm_core.__dict__.update(RESULTS=res, banner=print, load_model=lambda name, dev: name,
                            wm_vector=lambda model: FakeTensor(w))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "wm_core", wm_core)
    monkeypatch.setattr(demo_common, "RESULTS", res)
    return res


def test_e3_summary_records_public_checks(results, capsys):
    before = {who: json.loads((results / f"ezkl_hashed_{who}" / "summary.json").read_text()) for who in ("owner", "thief")}
    runpy.run_path(str(DEMO / "07_commitment_summary.py"), run_name="__main__")
    out = capsys.readouterr().out
    assert "owner proof verifies=True" in out and "-> ACCEPT" in out
    assert "REJECT (hash != published commitment)" in out
    for who in ("owner", "thief"):
        after = json.loads((results / f"ezkl_hashed_{who}" / "summary.json").read_text())
        assert {k: after[k] for k in before[who]} == before[who]          # no existing key removed or changed
        pc = after["public_checks"]
        assert pc["score"] == 64 and pc["input_matches_suspect_model"] is True
        assert pc["accepted"] is (who == "owner")
    assert json.loads((results / "ezkl_hashed_thief" / "summary.json").read_text())["public_checks"]["reasons"] == [
        "Poseidon commitment to the private params != the published commitment"]


@pytest.fixture
def fake_ezkl(results, monkeypatch):
    calls = []
    ezkl = types.ModuleType("ezkl")

    def touch(path, data=b"x"):
        Path(path).write_bytes(data)

    def compile_circuit(onnx, compiled, settings):
        assert Path(onnx).exists(), onnx
        touch(compiled)

    def prove(witness, compiled, pk, proof, srs_path=None):
        shutil.copy(results / "ezkl_private_thief" / "proof.json", proof)

    ezkl.compile_circuit = compile_circuit
    ezkl.gen_witness = lambda data, compiled, witness, srs_path=None: touch(witness)
    ezkl.setup = lambda compiled, vk, pk, srs_path=None: (touch(vk, b"vk"), touch(pk, b"pk"))
    ezkl.prove = prove
    ezkl.verify = lambda proof, settings, vk, srs_path=None: calls.append(proof) or True
    monkeypatch.setitem(sys.modules, "ezkl", ezkl)
    (results / "ezkl_private_owner" / "vk.key").write_bytes(b"vk")
    (results / "ezkl_private_thief" / "extract.onnx").write_bytes(b"thief onnx")
    return calls


def test_e2_records_public_checks_and_deletes_circuit_files(results, fake_ezkl, capsys, monkeypatch):
    monkeypatch.delenv("KEEP_ONNX", raising=False)
    runpy.run_path(str(DEMO / "06_vk_crosscheck.py"), run_name="__main__")
    out = capsys.readouterr().out
    # FIX-03: the thief's circuit model, the recompiled circuit and the witness are gone
    leftovers = [p.name for p in results.rglob("*") if p.name in ("extract.onnx", "thief.compiled", "witness.json")]
    assert leftovers == []
    vk = json.loads((results / "vk_crosscheck.json").read_text())
    assert vk["thief_verified_under_owner_vk"] is True and vk["identical"] is True
    for name in ("owner", "thief_under_owner_vk"):
        assert vk["public_checks"][name]["accepted"] is True, vk["public_checks"][name]
        assert vk["public_checks"][name]["score"] == 64
    assert "public signals, owner" in out and "cannot tell owner and thief apart" in out
