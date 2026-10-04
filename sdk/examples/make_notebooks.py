"""Builds the example notebooks (SDK-07) from the cells below, and with --run executes the same code as a
script so we know the notebooks work.

    .venv/Scripts/python sdk/examples/make_notebooks.py --run
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

COMMON_DATA = '''import gzip, numpy as np
from pathlib import Path
DATA = Path("../../demo/data")          # MNIST shipped with the repository
def idx(name):
    raw = gzip.open(DATA / name, "rb").read(); nd = raw[3]
    dims = [int.from_bytes(raw[4 + 4*i: 8 + 4*i], "big") for i in range(nd)]
    return np.frombuffer(raw, dtype=np.uint8, offset=4 + 4*nd).reshape(dims)
x = ((idx("train-images-idx3-ubyte.gz")[:12000] / 255.0 - 0.1307) / 0.3081).astype("float32")
y = idx("train-labels-idx1-ubyte.gz")[:12000].astype("int64")
xt = ((idx("t10k-images-idx3-ubyte.gz")[:2000] / 255.0 - 0.1307) / 0.3081).astype("float32")
yt = idx("t10k-labels-idx1-ubyte.gz")[:2000].astype("int64")
print(x.shape, xt.shape)'''

NOTEBOOKS = {
    "01_pytorch_quickstart.ipynb": [
        ("md", "# Watermark a PyTorch model and detect it\n\nThe owner creates an identity and a secret seed, "
               "embeds the watermark while training, and checks it on the quantised vector that a "
               "zero-knowledge proof would attest to. See `../../docs/protocol.md`."),
        ("code", COMMON_DATA),
        ("code", '''import torch, torch.nn as nn, torch.nn.functional as F
from sigil import protocol as P
from sigil.identity import KeyPair
from sigil.embed import embed_torch

class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1, self.conv2 = nn.Conv2d(1, 32, 3), nn.Conv2d(32, 64, 3)      # conv2: M = 32*3*3 = 288
        self.fc1, self.fc2 = nn.Linear(9216, 128), nn.Linear(128, 10)
    def forward(self, x):
        x = F.max_pool2d(F.relu(self.conv2(F.relu(self.conv1(x)))), 2)
        return self.fc2(F.relu(self.fc1(torch.flatten(x, 1))))

owner = KeyPair.generate()
cfg = P.Config(T=64, M=288, layer="conv2")
seed, pkh = P.new_seed(), P.pk_hash(owner.public_bytes)
torch.manual_seed(0)
model, det = embed_torch(Net(), (torch.from_numpy(x).unsqueeze(1), torch.from_numpy(y)), cfg, seed, pkh, epochs=1)
print(det)'''),
        ("code", '''with torch.no_grad():
    dev = next(model.parameters()).device
    acc = (model(torch.from_numpy(xt).unsqueeze(1).to(dev)).argmax(1).cpu().numpy() == yt).mean()
print(f"test accuracy {acc:.3f}")
torch.save(model.state_dict(), "watermarked.pt")
from sigil.adapters import detect
print("from file:", detect("watermarked.pt", seed, pkh, cfg))
print("someone else's key:", detect("watermarked.pt", P.new_seed(), pkh, cfg))
assert det.accepted'''),
    ],
    "02_keras_quickstart.ipynb": [
        ("md", "# Watermark a Keras model\n\nThe same protocol and the same kind of key as PyTorch: the "
               "Uchida vector is ordered (in, kh, kw) in every framework, so detection doesn't depend on "
               "where the model came from."),
        ("code", COMMON_DATA),
        ("code", '''import keras
from sigil import protocol as P
from sigil.identity import KeyPair
from sigil.embed import embed_keras

keras.utils.set_random_seed(0)
model = keras.Sequential([
    keras.Input((28, 28, 1)),
    keras.layers.Conv2D(32, 3, activation="relu", name="conv1"),
    keras.layers.Conv2D(64, 3, activation="relu", name="conv2"),     # HWIO kernel; M = 3*3*32 = 288
    keras.layers.MaxPooling2D(), keras.layers.Flatten(),
    keras.layers.Dense(128, activation="relu"), keras.layers.Dense(10),
])
owner = KeyPair.generate()
cfg = P.Config(T=64, M=288, layer="conv2")
seed, pkh = P.new_seed(), P.pk_hash(owner.public_bytes)
model, det = embed_keras(model, (x[..., None], y), cfg, seed, pkh, epochs=1)
print(det)'''),
        ("code", '''model.save("watermarked.keras")
from sigil.adapters import detect
print("from .keras:", detect("watermarked.keras", seed, pkh, cfg))
assert det.accepted'''),
    ],
    "03_verify_any_format.ipynb": [
        ("md", "# One watermark, three file formats\n\nA verifier may receive the suspect model as `.pt`, "
               "`.onnx` or a Keras file. The SDK reads the same layer from each and gets the identical "
               "quantised vector, hence the same `w_hash` that a proof is bound to."),
        ("code", COMMON_DATA),
        ("code", '''import torch, torch.nn as nn, torch.nn.functional as F
from sigil import protocol as P
from sigil.embed import embed_torch
from sigil.adapters import quantized_vector

class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1, self.conv2 = nn.Conv2d(1, 32, 3), nn.Conv2d(32, 64, 3)
        self.fc1, self.fc2 = nn.Linear(9216, 128), nn.Linear(128, 10)
    def forward(self, x):
        x = F.max_pool2d(F.relu(self.conv2(F.relu(self.conv1(x)))), 2)
        return self.fc2(F.relu(self.fc1(torch.flatten(x, 1))))

cfg = P.Config()
seed, pkh = P.new_seed(), P.pk_hash(bytes(32))
torch.manual_seed(0)
model, det = embed_torch(Net(), (torch.from_numpy(x).unsqueeze(1), torch.from_numpy(y)), cfg, seed, pkh, epochs=1)
model = model.cpu().eval()
torch.save(model.state_dict(), "suspect.pt")
torch.onnx.export(model, (torch.zeros(1, 1, 28, 28),), "suspect.onnx", dynamo=False, do_constant_folding=False)
q_pt, q_onnx = quantized_vector("suspect.pt", cfg), quantized_vector("suspect.onnx", cfg)
print("identical vectors:", (q_pt == q_onnx).all())
print("w_hash .pt  :", P.w_hash(q_pt, cfg))
print("w_hash .onnx:", P.w_hash(q_onnx, cfg))
assert (q_pt == q_onnx).all()'''),
    ],
}


def notebook(cells):
    def cell(kind, src):
        lines = src.splitlines(keepends=True)
        if kind == "md":
            return {"cell_type": "markdown", "metadata": {}, "source": lines}
        return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": lines}
    return {"nbformat": 4, "nbformat_minor": 5, "cells": [cell(k, s) for k, s in cells],
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                         "language_info": {"name": "python"}}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="also execute each notebook's code as a script")
    args = ap.parse_args()
    ok = True
    for name, cells in NOTEBOOKS.items():
        (HERE / name).write_text(json.dumps(notebook(cells), indent=1) + "\n", encoding="utf-8")
        print("wrote", name)
        if args.run:
            code = "\n\n".join(s for k, s in cells if k == "code")
            with tempfile.TemporaryDirectory(dir=HERE) as tmp:
                script = Path(tmp) / "nb.py"
                script.write_text(code.replace('Path("../../demo/data")', f'Path(r"{HERE.parents[1] / "demo" / "data"}")'),
                                  encoding="utf-8")
                r = subprocess.run([sys.executable, str(script)], cwd=tmp, capture_output=True, text=True,
                                   env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
                print(("   PASS " if r.returncode == 0 else "   FAIL ") + name)
                print("   " + "\n   ".join((r.stdout or r.stderr).strip().splitlines()[-6:]))
                ok &= r.returncode == 0
    sys.exit(0 if ok else 1)
