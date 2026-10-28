"""python -m backend.app [--port 8765] [--simulate] [--ui DIR] [--open]

Starts the backend on 127.0.0.1 (the same flags as demo/server.py). Equivalent to
`uvicorn backend.app.main:app --host 127.0.0.1 --port 8765` with SIGIL_SIMULATE / SIGIL_UI_DIR set.
"""
from __future__ import annotations

import argparse
import os
import webbrowser


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m backend.app", description="Sigil backend (FastAPI)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--simulate", action="store_true", help="v1 runs replay recorded logs (no torch/ezkl needed)")
    ap.add_argument("--ui", help="static UI build to serve (default frontend/dist; env SIGIL_UI_DIR)")
    ap.add_argument("--open", action="store_true", help="open the browser")
    a = ap.parse_args()
    if a.simulate:
        os.environ["SIGIL_SIMULATE"] = "1"
    if a.ui:
        os.environ["SIGIL_UI_DIR"] = a.ui
    import uvicorn
    url = f"http://127.0.0.1:{a.port}"
    print(f"Sigil backend: {url}   (Ctrl+C to stop)", flush=True)
    if a.open and not os.environ.get("DEMO_NO_BROWSER"):
        webbrowser.open(url)
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=a.port, timeout_graceful_shutdown=5,
                log_config=None)


if __name__ == "__main__":
    main()
