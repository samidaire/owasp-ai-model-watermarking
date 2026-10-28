"""`sigil embed` and `sigil attack` (SDK-03, ROB-01) on a tiny network, CPU only."""
import json
import sys

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from sigil.cli import main  # noqa: E402

pytestmark = pytest.mark.ml

TINY = '''
import torch.nn as nn
import torch.nn.functional as F


class Tiny(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 4, 3, padding=1)
        self.conv2 = nn.Conv2d(4, 8, 3, padding=1)
        self.fc = nn.Linear(8 * 8 * 8, 10)

    def forward(self, x):
        return self.fc(F.relu(self.conv2(F.relu(self.conv1(x)))).flatten(1))
'''


@pytest.fixture
def work(tmp_path, monkeypatch, capsys):
    """A folder with the Tiny architecture, a model file, data, and an owner key + T=16 seed for conv2 (M=36)."""
    monkeypatch.setenv("SIGIL_PASSPHRASE", "owner passphrase")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "tinynet", raising=False)
    (tmp_path / "tinynet.py").write_text(TINY)
    torch.manual_seed(0)
    from tinynet import Tiny
    torch.save(Tiny().state_dict(), tmp_path / "model.pt")
    rng = np.random.default_rng(0)
    np.savez(tmp_path / "data.npz", x=rng.normal(size=(256, 1, 8, 8)).astype(np.float32), y=rng.integers(0, 10, 256))

    def run(*args):
        code = main(["--json", *args])
        out = capsys.readouterr().out
        return code, (json.loads(out) if out.strip() else None)
    assert run("keygen", "--out", "secrets/owner.key")[0] == 0
    assert run("seed", "--bits", "16", "--m", "36", "--layer", "conv2")[0] == 0
    return run


def _load(path):
    from tinynet import Tiny
    m = Tiny()
    m.load_state_dict(torch.load(path, weights_only=True))
    return m.eval()


def test_embed_then_detect(work, tmp_path):
    code, out = work("embed", "model.pt", "--arch", "tinynet:Tiny", "--data", "data.npz", "--epochs", "30",
                     "--batch-size", "32", "--lr", "0.01")
    assert code == 0 and out["accepted"] and out["errors"] <= out["max_err"] == 2
    assert out["model"].endswith("model.wm.pt") and out["layer"] == "conv2"
    code, det = work("detect", "model.wm.pt")
    assert code == 0 and det["accepted"]
    assert not work("detect", "model.pt")[1]["accepted"]          # the unmarked original


def test_embed_saves_nothing_when_the_mark_does_not_take(work, tmp_path):
    with pytest.raises(SystemExit, match="didn't take"):
        work("embed", "model.pt", "--arch", "tinynet:Tiny", "--data", "data.npz", "--epochs", "0")
    assert not (tmp_path / "model.wm.pt").exists()


def test_embed_needs_arch_for_pt_and_x_y_arrays(work, tmp_path):
    assert work("embed", "model.pt", "--data", "data.npz")[0] == 2
    np.savez(tmp_path / "bad.npz", inputs=np.zeros(3))
    assert work("embed", "model.pt", "--arch", "tinynet:Tiny", "--data", "bad.npz")[0] == 2
    assert work("embed", "model.pt", "--arch", "tinynet", "--data", "data.npz")[0] == 2      # not module:callable


def test_attacks_that_need_no_data(work, tmp_path):
    code, out = work("attack", "prune", "model.pt", "--arch", "tinynet:Tiny", "--ratio", "0.5")
    assert code == 0 and out["model"].endswith("model.prune.pt")
    w = _load("model.prune.pt").conv2.weight
    assert (w == 0).float().mean() >= 0.5
    work("attack", "quantize", "model.pt", "--arch", "tinynet:Tiny", "--bits", "4", "--granularity", "tensor")
    assert _load("model.quantize.pt").conv2.weight.unique().numel() <= 16
    work("attack", "permute", "model.pt", "--arch", "tinynet:Tiny", "--producer", "conv1", "--consumer", "conv2")
    x = torch.randn(4, 1, 8, 8)
    assert torch.allclose(_load("model.pt")(x), _load("model.permute.pt")(x), atol=1e-5)
    assert not torch.equal(_load("model.pt").conv2.weight, _load("model.permute.pt").conv2.weight)
    for name, extra in (("kmeans", ["--clusters", "4"]), ("low-rank", ["--rank-fraction", "0.25"]),
                        ("prune-channels", [])):
        assert work("attack", name, "model.pt", "--arch", "tinynet:Tiny", *extra)[0] == 0


def test_attacks_that_train(work, tmp_path):
    common = ["model.pt", "--arch", "tinynet:Tiny", "--data", "data.npz", "--epochs", "1"]
    code, out = work("attack", "ftal", *common, "--eval", "data.npz")
    assert code == 0 and 0 <= out["accuracy_before"] <= 1 and 0 <= out["accuracy_after"] <= 1
    assert work("attack", "overwrite", *common, "--layer", "conv2", "--thief-bits", "16")[0] == 0
    code, out = work("attack", "extract", *common, "--budget", "64")
    assert code == 0 and out["queries"] == 64
    assert work("attack", "ftal", "model.pt", "--arch", "tinynet:Tiny")[0] == 2          # no --data
    assert work("attack", "fine-prune", *common)[0] == 2                                  # no --layer


def test_attack_refuses_non_pytorch_files(work, tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"not used")
    assert work("attack", "prune", "model.onnx")[0] == 2


def test_embed_keras(work, tmp_path):
    keras = pytest.importorskip("keras")
    keras.utils.set_random_seed(0)
    model = keras.Sequential([keras.Input((8, 8, 1)), keras.layers.Conv2D(4, 3, padding="same", name="conv1"),
                              keras.layers.Conv2D(8, 3, padding="same", name="conv2"), keras.layers.Flatten(),
                              keras.layers.Dense(10, name="fc")])
    model.save(tmp_path / "k.keras")
    d = np.load(tmp_path / "data.npz")
    np.savez(tmp_path / "nhwc.npz", x=d["x"].transpose(0, 2, 3, 1), y=d["y"])
    code, out = work("embed", "k.keras", "--data", "nhwc.npz", "--epochs", "30", "--batch-size", "32", "--lr", "0.01")
    assert code == 0 and out["framework"] == "keras" and out["model"].endswith("k.wm.keras")
    assert work("detect", "k.wm.keras")[1]["accepted"]
