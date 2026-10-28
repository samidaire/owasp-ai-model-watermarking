"""CIFAR-10 data (from the official python archive) and the CIFAR-style ResNet-18 used for evaluation (DEC-04).

Data: https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz, extracted into experiments/data/ (gitignored).
The archive's MD5 is checked before its batches are unpickled (pickle is only used on this verified file).
Split: owner = train[0:40000], attacker = train[40000:50000] (disjoint, ROB-04), test = test_batch (10k).
"""
from __future__ import annotations

import hashlib
import pickle
import tarfile
import urllib.request

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from common import DATA, log

URL = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"
MD5 = "c58f30108f718f92721af3b95e74349a"
MEAN = [0.4914, 0.4822, 0.4465]
STD = [0.2470, 0.2435, 0.2616]
OWNER_N = 40000


def _ensure_archive():
    folder = DATA / "cifar-10-batches-py"
    tgz = DATA / "cifar-10-python.tar.gz"
    if not tgz.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        log(f"downloading {URL}")
        urllib.request.urlretrieve(URL, tgz)
    if hashlib.md5(tgz.read_bytes()).hexdigest() != MD5:
        raise RuntimeError(f"{tgz} does not have the official MD5 {MD5}")
    if not (folder / "test_batch").exists():
        with tarfile.open(tgz) as t:
            t.extractall(DATA, filter="data")
    return folder


def load_cifar(dev) -> dict:
    folder = _ensure_archive()

    def batch(name):
        with open(folder / name, "rb") as f:
            d = pickle.load(f, encoding="bytes")
        return np.asarray(d[b"data"], dtype=np.uint8).reshape(-1, 3, 32, 32), np.asarray(d[b"labels"], dtype=np.int64)

    parts = [batch(f"data_batch_{i}") for i in range(1, 6)]
    xtr, ytr = np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])
    xte, yte = batch("test_batch")
    m = torch.tensor(MEAN).view(1, 3, 1, 1)
    s = torch.tensor(STD).view(1, 3, 1, 1)

    def norm(x):
        return ((torch.from_numpy(x).float() / 255.0) - m) / s

    out = {"x_owner": norm(xtr[:OWNER_N]), "y_owner": torch.from_numpy(ytr[:OWNER_N]),
           "x_att": norm(xtr[OWNER_N:]), "y_att": torch.from_numpy(ytr[OWNER_N:]),
           "x_test": norm(xte), "y_test": torch.from_numpy(yte)}
    return {k: v.to(dev) for k, v in out.items()}


def augment(x: torch.Tensor, g: torch.Generator) -> torch.Tensor:
    """Standard CIFAR augmentation on the GPU: random 32x32 crop of the 4-pixel zero-padded image (zero in
    normalised space) and a random horizontal flip. Randomness from the training loop's seeded generator."""
    n = x.shape[0]
    ox = torch.randint(0, 9, (n,), generator=g).to(x.device)
    oy = torch.randint(0, 9, (n,), generator=g).to(x.device)
    flip = (torch.rand(n, generator=g) < 0.5).to(x.device)
    xp = F.pad(x, (4, 4, 4, 4))
    ar = torch.arange(32, device=x.device)
    rows = (oy[:, None] + ar)[:, None, :, None]
    cols = (ox[:, None] + ar)
    cols = torch.where(flip[:, None], cols.flip(1), cols)[:, None, None, :]
    return xp[torch.arange(n, device=x.device)[:, None, None, None], torch.arange(3, device=x.device)[None, :, None, None],
              rows, cols]


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, cin, cout, stride=1):
        super().__init__()
        self.conv1 = nn.Conv2d(cin, cout, 3, stride, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(cout)
        self.conv2 = nn.Conv2d(cout, cout, 3, 1, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(cout)
        self.shortcut = nn.Sequential()
        if stride != 1 or cin != cout:
            self.shortcut = nn.Sequential(nn.Conv2d(cin, cout, 1, stride, bias=False), nn.BatchNorm2d(cout))

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        return F.relu(out + self.shortcut(x))


class ResNet18(nn.Module):
    """CIFAR ResNet-18 (He et al. 2016; 3x3 stem, no max-pool), 11.2M parameters."""

    def __init__(self, num_classes=10):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 64, 3, 1, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        cin, layers = 64, []
        for cout, stride in ((64, 1), (128, 2), (256, 2), (512, 2)):
            layers.append(nn.Sequential(BasicBlock(cin, cout, stride), BasicBlock(cout, cout, 1)))
            cin = cout
        self.layer1, self.layer2, self.layer3, self.layer4 = layers
        self.linear = nn.Linear(512, num_classes)

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.layer4(self.layer3(self.layer2(self.layer1(out))))
        out = F.adaptive_avg_pool2d(out, 1).flatten(1)
        return self.linear(out)
