"""Rebuild the user guide PDF (Sigil-User-Guide.pdf at the repo root) from guide.html.

    python demo/server.py --simulate            # in one terminal (screenshots come from the live UI)
    .venv/Scripts/python docs/guide/build.py    # Windows; needs Node 20+, Microsoft Edge and Pillow
    .venv/Scripts/python docs/guide/build.py --no-shots   # re-render the PDF with the existing screenshots
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EDGE = os.environ.get("EDGE", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

if "--no-shots" not in sys.argv:
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["node", str(HERE / "make_screenshots.mjs"), tmp], check=True, env={**os.environ, "EDGE": EDGE})
        for png in sorted(Path(tmp).glob("*.png")):
            Image.open(png).convert("RGB").save(HERE / "img" / f"{png.stem}.jpg", "JPEG", quality=86, optimize=True, progressive=True)

with tempfile.TemporaryDirectory() as profile:
    pdf = ROOT / "Sigil-User-Guide.pdf"
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                    "--no-pdf-header-footer", "--generate-pdf-document-outline", "--virtual-time-budget=5000",
                    f"--print-to-pdf={pdf}", (HERE / "guide.html").as_uri()], check=True)
print(f"{pdf}  ({pdf.stat().st_size / 2**20:.1f} MiB)")
