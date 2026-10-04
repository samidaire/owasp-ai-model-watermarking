"""NFR-01: fail if a built UI would load anything from the network at runtime.

Checks what a browser actually fetches (HTML src/href, CSS url()/@import, JS fetch/import/EventSource),
not every URL-looking string: bundled libraries legitimately contain documentation links.

    python scripts/check_offline_build.py frontend/dist
"""
import re
import sys
from pathlib import Path

ALLOWED = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])([:/]|$)")
PATTERNS = {
    ".html": [r"""(?:src|href)\s*=\s*["'](https?://[^"']+)"""],
    ".css": [r"""url\(\s*["']?(https?://[^"')]+)""", r"""@import\s+(?:url\()?["']?(https?://[^"')\s;]+)"""],
    ".js": [r"""fetch\(\s*["'`](https?://[^"'`]+)""", r"""import\(\s*["'`](https?://[^"'`]+)""",
            r"""EventSource\(\s*["'`](https?://[^"'`]+)""", r"""\.src\s*=\s*["'`](https?://[^"'`]+)"""],
}


def scan(root: Path) -> list[str]:
    bad = []
    for path in root.rglob("*"):
        pats = PATTERNS.get(path.suffix.lower())
        if not pats or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in pats:
            for url in re.findall(pat, text):
                if not ALLOWED.match(url):
                    bad.append(f"{path.relative_to(root)}: {url}")
    return bad


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/dist")
    if not root.is_dir():
        sys.exit(f"no build at {root}")
    problems = scan(root)
    for p in problems:
        print("external runtime URL:", p)
    print(f"{root}: {'FAIL' if problems else 'ok'} ({len(problems)} external runtime URLs)")
    sys.exit(1 if problems else 0)
