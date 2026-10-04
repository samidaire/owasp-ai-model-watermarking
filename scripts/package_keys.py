"""Package the Groth16 proving artefacts so another machine can prove without running the setup.

    .venv/Scripts/python scripts/package_keys.py            # -> dist/sigil-proving-keys.zip
    .venv/Scripts/python scripts/package_keys.py --t64-only # smaller zip (~100 MB)

The receiving machine installs them with `setup.ps1 --keys <zip>` (or setup.sh), which checks every
zkey's SHA-256 against the committed circuits/keys/<circuit>.setup.json before accepting it. Proving
keys are public (they reveal nothing secret); the verification keys are already in git.
"""
import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "circuits" / "build"

ap = argparse.ArgumentParser()
ap.add_argument("--t64-only", action="store_true")
ap.add_argument("--out", type=Path, default=ROOT / "dist" / "sigil-proving-keys.zip")
args = ap.parse_args()
args.out.parent.mkdir(parents=True, exist_ok=True)
n = 0
with zipfile.ZipFile(args.out, "w", zipfile.ZIP_STORED) as z:          # zkeys don't compress
    for t in sorted((ROOT / "circuits" / "keys").glob("*.setup.json")):
        name = json.loads(t.read_text())["circuit"]
        if args.t64_only and "_T64_" not in name:
            continue
        files = [BUILD / f"{name}.zkey", BUILD / f"{name}.r1cs", BUILD / f"{name}.srchash",
                 BUILD / f"{name}_js" / f"{name}.wasm"]
        missing = [f.name for f in files if not f.exists()]
        if missing:
            print(f"skip {name}: missing {missing} (run `sigil zk-setup` first)")
            continue
        for f in files:
            z.write(f, f.relative_to(BUILD).as_posix())
            n += 1
        print(f"added {name}")
print(f"{args.out}: {n} files, {args.out.stat().st_size / 2**20:.0f} MiB")
