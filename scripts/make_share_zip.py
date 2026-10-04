"""Make ONE zip to hand to a teammate: the repository at HEAD plus the T=64 proving keys.

    .venv/Scripts/python scripts/make_share_zip.py      # -> dist/owasp-wm-demo.zip

On the other machine: unzip, then run setup.ps1 --demo (Windows) or ./setup.sh --demo. The setup finds
dist/sigil-proving-keys-t64.zip inside and installs it (each key is checked against circuits/keys/).
Only committed files are included: no .venv, node_modules, secrets/ or build outputs.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
keys = DIST / "sigil-proving-keys-t64.zip"
if not keys.exists():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "package_keys.py"), "--t64-only", "--out", str(keys)], check=True)
if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
    print("note: uncommitted changes are NOT included (the zip is built from HEAD)")
repo = DIST / "repo-head.zip"
subprocess.run(["git", "archive", "--format=zip", "--prefix=owasp-ai-model-watermarking/", "-o", str(repo), "HEAD"],
               cwd=ROOT, check=True)
out = DIST / "owasp-wm-demo.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    with zipfile.ZipFile(repo) as r:
        for info in r.infolist():
            z.writestr(info, r.read(info))
    z.write(keys, "owasp-ai-model-watermarking/dist/sigil-proving-keys-t64.zip", compress_type=zipfile.ZIP_STORED)
repo.unlink()
commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
print(f"{out}  ({out.stat().st_size / 2**20:.0f} MiB, commit {commit})")
