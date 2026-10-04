"""demo/01_train.py is transactional (FIX-12): a failed retrain never touches the owner secret,
the public commitment or the checkpoints. torch and wm_core are replaced by small stand-ins so
the script's file handling runs for real without the ML stack."""
import hashlib
import json
import runpy
import sys
import types
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "demo" / "01_train.py"


class FakeTensor:
    def __init__(self, a):
        self.a = np.asarray(a)
        self.shape = self.a.shape

    def to(self, dev):
        return self

    def tolist(self):
        return self.a.tolist()


class FakeNet:
    def to(self, dev):
        return self

    def state_dict(self):
        return {}


@pytest.fixture
def demo(tmp_path, monkeypatch):
    ckpt, results = tmp_path / "ckpt", tmp_path / "results"
    ckpt.mkdir()
    results.mkdir()
    old = {ckpt / "owner_secret.json": b'{"owner_id": "owner:yash", "seed_hex": "00"}',
           results / "public_commitment.json": b'{"commitment_sha256": "old"}',
           ckpt / "clean.pt": b"old-clean", ckpt / "watermarked.pt": b"old-wm", ckpt / "null_0.pt": b"old-null"}
    for p, data in old.items():
        p.write_bytes(data)

    calls = {"fail_on": None, "summary_saw_secret": None}

    torch = types.ModuleType("torch")
    torch.from_numpy = FakeTensor
    torch.manual_seed = lambda n: None
    torch.save = lambda obj, path: Path(path).write_bytes(b"new-" + Path(path).stem.encode())

    def train(model, x, y, epochs, seed=0, wm=None, tag=""):
        if tag == calls["fail_on"]:
            raise RuntimeError(f"CUDA out of memory while training {tag}")
        return model

    def write_train_summary(dev, d, epochs=None):
        calls["summary_saw_secret"] = json.loads((ckpt / "owner_secret.json").read_text())

    wm_core = types.ModuleType("wm_core")
    wm_core.__dict__.update(
        CKPT=ckpt, RESULTS=results, OWNER_ID="owner:yash", Net=FakeNet, accuracy=lambda m, x, y: 0.99,
        banner=print, ber=lambda bits, b: 0.0, device=lambda: "cpu", load_mnist=lambda dev: {k: None for k in (
            "x_owner", "y_owner", "x_test", "y_test")},
        commitment=lambda seed, oid: hashlib.sha256(b"commit|" + seed + b"|" + oid.encode()).hexdigest(),
        derive_key=lambda seed: np.zeros((64, 288), np.float32),
        derive_signature=lambda seed, oid: np.zeros(64, np.uint8),
        extract_bits=lambda m, X: np.zeros(64, np.uint8), train=train, utc_now=lambda: "2026-10-05T00:00:00+00:00",
        write_train_summary=write_train_summary)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "wm_core", wm_core)
    monkeypatch.setattr(sys, "argv", ["01_train.py", "--nulls", "2"])
    return types.SimpleNamespace(ckpt=ckpt, results=results, old=old, calls=calls)


def run_script():
    runpy.run_path(str(SCRIPT), run_name="__main__")


@pytest.mark.parametrize("fail_on", ["clean", "watermarked", "null_1"])
def test_failed_retrain_changes_nothing(demo, fail_on):
    demo.calls["fail_on"] = fail_on
    with pytest.raises(RuntimeError, match="out of memory"):
        run_script()
    for p, data in demo.old.items():
        assert p.read_bytes() == data, p
    assert sorted(p.name for p in demo.ckpt.iterdir()) == ["clean.pt", "null_0.pt", "owner_secret.json", "watermarked.pt"]
    assert sorted(p.name for p in demo.results.iterdir()) == ["public_commitment.json"]


def test_successful_retrain_swaps_in_and_backs_up(demo, capsys):
    run_script()
    secret = json.loads((demo.ckpt / "owner_secret.json").read_text())
    public = json.loads((demo.results / "public_commitment.json").read_text())
    assert secret["seed_hex"] != "00" and len(secret["seed_hex"]) == 64
    assert public["commitment_sha256"] == hashlib.sha256(
        b"commit|" + bytes.fromhex(secret["seed_hex"]) + b"|owner:yash").hexdigest()
    for name in ("clean", "watermarked", "null_0", "null_1"):
        assert (demo.ckpt / f"{name}.pt").read_bytes() == b"new-" + name.encode()
    assert not (demo.ckpt / ".staging").exists()
    # the train summary is written only after the swap, so it sees the NEW secret
    assert demo.calls["summary_saw_secret"] == secret

    backups = list((demo.ckpt / "backup").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "owner_secret.json").read_bytes() == demo.old[demo.ckpt / "owner_secret.json"]
    assert (backups[0] / "public_commitment.json").read_bytes() == demo.old[demo.results / "public_commitment.json"]
    out = capsys.readouterr().out
    assert f"backed up to ckpt/backup/{backups[0].name}/" in out and str(demo.ckpt) not in out

    run_script()                                         # a second retrain gets its own backup folder
    assert len(list((demo.ckpt / "backup").iterdir())) == 2
