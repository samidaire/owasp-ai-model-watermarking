"""One-command setup on a fresh machine (NFR-02, NFR-06). Standard library only.

    python scripts/setup_env.py                    # full live setup (auto GPU/CPU PyTorch)
    python scripts/setup_env.py --keys sigil-proving-keys.zip   # + the shipped proving keys (skip zk setup)
    python scripts/setup_env.py --minimal          # just the demo UI with saved results (nothing to install)

Steps (each skipped when already done):
  1. uv (fast Python installer) and a project venv in .venv with Python 3.12
  2. PyTorch: CUDA build if an NVIDIA GPU is found (nvidia-smi), else CPU (--cpu forces CPU)
  3. demo requirements, the sigil SDK with extras (torch, onnx, tf unless --no-tf), the backend
  4. Node packages for the circuits (circomlib, SnarkJS) and the circom compiler in tools/bin
  5. proving keys: unpack --keys ZIP (checked against circuits/keys/*.setup.json), or --zk-setup to
     generate them here (~3 min for T=64; downloads a 144 MB Powers of Tau file once)
  6. a quick self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IS_WIN = os.name == "nt"
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
TORCH_VERSION = "2.14.1"
CIRCOM_VERSION = "v2.2.3"
CIRCOM_ASSET = {"Windows": "circom-windows-amd64.exe", "Linux": "circom-linux-amd64", "Darwin": "circom-macos-amd64"}


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def run(cmd: list, cwd: Path | None = None, check: bool = True) -> int:
    print("   $", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=cwd, check=check).returncode


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def uv() -> list[str]:
    if have("uv"):
        return ["uv"]
    try:
        subprocess.run([sys.executable, "-m", "uv", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        run([sys.executable, "-m", "pip", "install", "--user", "--quiet", "uv"])
    return [sys.executable, "-m", "uv"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gpu_present() -> bool:
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=20).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def python_env(args) -> None:
    u = uv()
    if not VENV_PY.exists():
        step("Python 3.12 virtual environment (.venv)")
        run([*u, "python", "install", "3.12"])
        run([*u, "venv", "--python", "3.12", str(ROOT / ".venv")])
    pip = [*u, "pip", "install", "--python", str(VENV_PY)]
    cuda = not args.cpu and gpu_present()
    step(f"PyTorch {TORCH_VERSION} ({'CUDA 13.0 build' if cuda else 'CPU build'})")
    index = "https://download.pytorch.org/whl/cu130" if cuda else "https://download.pytorch.org/whl/cpu"
    run([*pip, f"torch=={TORCH_VERSION}", "--index-url", index])
    step("demo requirements, sigil SDK, backend")
    run([*pip, "-r", str(ROOT / "demo" / "requirements.txt")])
    extras = "torch,onnx,dev" + ("" if args.no_tf else ",tf")
    run([*pip, "-e", f"{ROOT / 'sdk'}[{extras}]"])
    backend_req = ROOT / "backend" / "requirements.txt"
    if backend_req.exists():
        run([*pip, "-r", str(backend_req)])


def node_env() -> None:
    step("circuit toolchain (circomlib, SnarkJS) and the circom compiler")
    if not have("node") or not have("npm"):
        sys.exit("Node.js 20.19+ is required for the zero-knowledge proofs: install it from https://nodejs.org")
    npm = "npm.cmd" if IS_WIN else "npm"
    run([npm, "ci", "--no-audit", "--no-fund"], cwd=ROOT / "circuits")
    bin_dir = ROOT / "tools" / "bin"
    target = bin_dir / ("circom.exe" if IS_WIN else "circom")
    if not target.exists():
        asset = CIRCOM_ASSET.get(platform.system())
        if not asset:
            sys.exit(f"no prebuilt circom for {platform.system()}; build it from https://github.com/iden3/circom")
        bin_dir.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/iden3/circom/releases/download/{CIRCOM_VERSION}/{asset}"
        print(f"   downloading {url}")
        urllib.request.urlretrieve(url, target)
        if not IS_WIN:
            target.chmod(0o755)
    run([target, "--version"])


def unpack_keys(zip_path: Path) -> None:
    """Install shipped proving keys, refusing any that don't match the committed setup transcript."""
    step(f"proving keys from {zip_path.name}")
    build = ROOT / "circuits" / "build"
    build.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts or name.suffix not in (".zkey", ".wasm", ".r1cs", ".srchash"):
                print(f"   skipping {info.filename}")
                continue
            dest = build / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    for transcript in (ROOT / "circuits" / "keys").glob("*.setup.json"):
        t = json.loads(transcript.read_text())
        zkey = build / f"{t['circuit']}.zkey"
        if zkey.exists():
            if sha256(zkey) != t["zkey_sha256"]:
                zkey.unlink()
                sys.exit(f"{zkey.name} does not match {transcript.name}: refusing it (deleted)")
            print(f"   ok  {zkey.name} matches its setup transcript")


def self_test() -> None:
    step("self-test")
    run([VENV_PY, "-m", "sigil.cli", "--version"])
    run([VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not ml and not zk and not slow",
         str(ROOT / "sdk" / "tests"), str(ROOT / "tests")], check=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minimal", action="store_true", help="demo UI with saved results only: install nothing")
    ap.add_argument("--cpu", action="store_true", help="install the CPU build of PyTorch even if a GPU is present")
    ap.add_argument("--no-tf", action="store_true", help="skip TensorFlow/Keras (saves ~1 GB)")
    ap.add_argument("--keys", type=Path, help="zip of proving keys made by scripts/package_keys.py")
    ap.add_argument("--zk-setup", action="store_true", help="generate proving keys here instead (T=64)")
    args = ap.parse_args()
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10+ is needed to run this script")
    if args.minimal:
        print("Nothing to install. Start the demo UI with saved results:\n"
              f"   python {Path('demo') / 'server.py'} --simulate      (then open http://127.0.0.1:8765)")
        return
    python_env(args)
    node_env()
    if args.keys:
        unpack_keys(args.keys)
    elif args.zk_setup:
        step("Groth16 setup for the T=64 circuit (downloads the Powers of Tau once)")
        run([VENV_PY, "-m", "sigil.cli", "zk-setup", "--bits", "64"])
    self_test()
    print("\nDone. Start the app:   "
          + (r".venv\Scripts\python demo\server.py" if IS_WIN else ".venv/bin/python demo/server.py")
          + "   (add --simulate to replay saved runs)")


if __name__ == "__main__":
    main()
