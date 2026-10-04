"""Core library for the OWASP AI Model Watermarking demo.

Watermark: Uchida et al., "Embedding Watermarks into Deep Neural Networks" (ICMR 2017).
A T-bit signature b is embedded into w, the mean (over output filters) of one conv
layer's weights, via a BCE regulariser on sigmoid(X @ w). Extraction: b_hat = 1[X @ w >= 0].

Key management (the project's proposed fix, see 01 report section 7):
both the projection key X and the signature b are derived from one secret seed,
and only H(seed || owner_id) is published, with a timestamp, at embedding time.
"""
import copy
import gzip
import sys
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# Windows consoles default to cp1252 when piped; keep output UTF-8 everywhere.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CKPT = ROOT / "ckpt"
RESULTS = ROOT / "results"

T_BITS = 64            # signature length
M_DIM = 32 * 3 * 3     # Uchida vector length for conv2 (in_channels * k * k)
LAMBDA = 1.0           # watermark regulariser weight (mean-BCE)
THETA = 8 / 64         # indicative BER acceptance threshold for the demo (not calibrated)
OWNER_ID = "owner:yash"
THIEF_ID = "thief:mallory"


def device():
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def banner(title):
    line = "=" * 78
    print(f"\n{line}\n  {title}\n{line}")


# ----------------------------------------------------------------------------- data
def _read_idx(path):
    with gzip.open(path, "rb") as f:
        raw = f.read()
    ndim = raw[3]
    dims = [int.from_bytes(raw[4 + 4 * i: 8 + 4 * i], "big") for i in range(ndim)]
    return np.frombuffer(raw, dtype=np.uint8, offset=4 + 4 * ndim).reshape(dims)


def load_mnist(dev):
    """Returns dict of tensors on `dev`.
    owner: train[:50000]  attacker: train[50000:]  (10k in-domain samples)  test: t10k."""
    def imgs(name):
        x = _read_idx(DATA / name).astype(np.float32) / 255.0
        return torch.from_numpy((x - 0.1307) / 0.3081).unsqueeze(1)

    def labels(name):
        return torch.from_numpy(_read_idx(DATA / name).astype(np.int64))

    xtr, ytr = imgs("train-images-idx3-ubyte.gz"), labels("train-labels-idx1-ubyte.gz")
    xte, yte = imgs("t10k-images-idx3-ubyte.gz"), labels("t10k-labels-idx1-ubyte.gz")
    d = {
        "x_owner": xtr[:50000], "y_owner": ytr[:50000],
        "x_att": xtr[50000:], "y_att": ytr[50000:],
        "x_test": xte, "y_test": yte,
    }
    return {k: v.to(dev) for k, v in d.items()}


# ---------------------------------------------------------------------------- model
class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, 3)
        self.conv2 = nn.Conv2d(32, 64, 3)   # watermarked layer
        self.fc1 = nn.Linear(9216, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2)
        x = torch.flatten(x, 1)
        x = F.relu(self.fc1(x))
        return self.fc2(x)


def wm_vector(model):
    """Uchida: average the target layer's filters -> vector of length in_ch*k*k."""
    return model.conv2.weight.mean(dim=0).flatten()


def extract_bits(model, X):
    with torch.no_grad():
        return (X @ wm_vector(model) >= 0).to(torch.uint8)


def ber(bits, b):
    return float((bits != b).float().mean())


# ------------------------------------------------------------------ key derivation
def commitment(seed: bytes, owner_id: str) -> str:
    return hashlib.sha256(b"commit|" + seed + b"|" + owner_id.encode()).hexdigest()


def derive_signature(seed: bytes, owner_id: str, T=T_BITS) -> np.ndarray:
    h = hashlib.sha256(b"sig|" + seed + b"|" + owner_id.encode()).digest()
    return np.unpackbits(np.frombuffer(h, dtype=np.uint8))[:T]


def derive_key(seed: bytes, T=T_BITS, M=M_DIM) -> np.ndarray:
    h = hashlib.sha256(b"key|" + seed).digest()
    rng = np.random.Generator(np.random.PCG64(int.from_bytes(h, "big")))
    return rng.standard_normal((T, M), dtype=np.float32)


def text_to_bits(s: str) -> np.ndarray:
    return np.unpackbits(np.frombuffer(s.encode()[:T_BITS // 8].ljust(T_BITS // 8), dtype=np.uint8))


def bits_to_text(bits) -> str:
    return np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes().decode(errors="replace")


def binom_tail_le(n, k, p=0.5):
    """P[Bin(n,p) <= k]: chance a random key/signature pair passes at threshold k/n."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


# ------------------------------------------------------------------ train / eval
def train(model, x, y, epochs, lr=1e-3, bs=128, wm=None, lam=LAMBDA, seed=0, tag=""):
    """wm = (X tensor [T,M], b tensor [T]) to embed a watermark, or None."""
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    g = torch.Generator().manual_seed(seed)
    n = x.shape[0]
    for ep in range(epochs):
        model.train()
        t0 = time.time()
        perm = torch.randperm(n, generator=g).to(x.device)
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            loss = F.cross_entropy(model(x[idx]), y[idx])
            if wm is not None:
                X, b = wm
                loss = loss + lam * F.binary_cross_entropy_with_logits(X @ wm_vector(model), b.float())
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        msg = f"  [{tag}] epoch {ep + 1}/{epochs}  loss={loss.item():.4f}  ({time.time() - t0:.1f}s)"
        if wm is not None:
            msg += f"  BER={ber(extract_bits(model, wm[0]), wm[1]):.3f}"
        print(msg)
    model.eval()
    return model


@torch.no_grad()
def accuracy(model, x, y, bs=2000):
    model.eval()
    correct = 0
    for i in range(0, x.shape[0], bs):
        correct += (model(x[i:i + bs]).argmax(1) == y[i:i + bs]).sum().item()
    return correct / x.shape[0]


# ------------------------------------------------------------------ persistence
def save_model(model, name):
    CKPT.mkdir(exist_ok=True)
    torch.save(model.state_dict(), CKPT / f"{name}.pt")


def load_model(name, dev):
    m = Net().to(dev)
    m.load_state_dict(torch.load(CKPT / f"{name}.pt", map_location=dev))
    m.eval()
    return m


def load_owner(dev):
    """Owner's private secret + public commitment, plus derived (X, b) tensors."""
    secret = json.loads((CKPT / "owner_secret.json").read_text())
    public = json.loads((RESULTS / "public_commitment.json").read_text())
    seed = bytes.fromhex(secret["seed_hex"])
    X = torch.from_numpy(derive_key(seed)).to(dev)
    b = torch.from_numpy(derive_signature(seed, secret["owner_id"])).to(dev)
    return seed, secret, public, X, b


def null_model_names():
    return sorted(p.stem for p in CKPT.glob("null_*.pt"))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clone(model):
    return copy.deepcopy(model)


# ------------------------------------------------------------------ web UI summaries
def write_train_summary(dev, d, epochs=None):
    """Structured summary of demo A for the web UI (results/train.json). Read-only: no training."""
    from demo_common import write_json
    seed, secret, public, X, b = load_owner(dev)
    models = {"clean": load_model("clean", dev), "watermarked": load_model("watermarked", dev)}
    out = {
        "commitment": public["commitment_sha256"], "timestamp_utc": public["timestamp_utc"],
        "owner_id": secret["owner_id"], "scheme": public["scheme"], "device": str(dev), "epochs": epochs,
        "threshold": THETA, "key_shape": list(X.shape), "signature_bits": b.tolist(),
        "models": {}, "nulls": [],
    }
    for name, m in models.items():
        bits = extract_bits(m, X)
        out["models"][name] = {"accuracy": accuracy(m, d["x_test"], d["y_test"]),
                               "owner_ber": ber(bits, b), "extracted_bits": bits.tolist()}
    for n in null_model_names():
        m = load_model(n, dev)
        out["nulls"].append({"name": n, "accuracy": accuracy(m, d["x_test"], d["y_test"]),
                             "owner_ber": ber(extract_bits(m, X), b)})
    write_json("train.json", out)
    return out
