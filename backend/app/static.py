"""Result files and the static UI (API-01, API-02): /results/{file} with Cache-Control: no-cache, and the UI
build (SIGIL_UI_DIR, default frontend/dist) with SPA fallback. Registered last: the UI route catches all GETs."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from . import legacy
from .problems import is_v2, problem_response, v1_error

router = APIRouter(include_in_schema=False)
RESULT_SUFFIXES = (".png", ".csv", ".json", ".txt")


def _file(path: Path, cache: str | None = None) -> FileResponse:
    ctype = legacy.CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] \
        or "application/octet-stream"
    cache = cache or ("no-cache" if path.suffix == ".html" else "max-age=3600")
    return FileResponse(path, media_type=ctype, headers={"Cache-Control": cache})


@router.get("/results/{name:path}")
def result_file(name: str, request: Request):
    f = legacy.safe_join(Path(request.app.state.settings.results_dir), name)
    if f and f.suffix in RESULT_SUFFIXES:
        return _file(f, cache="no-cache")              # re-runs must show fresh files
    return v1_error(404, "not found")


@router.get("/{path:path}")
def ui(path: str, request: Request):
    if is_v2("/" + path):
        return problem_response(request, 404, "no such endpoint")
    if path == "api" or path.startswith("api/"):
        return v1_error(404, "not found")
    ui_dir = Path(request.app.state.settings.ui_dir).resolve()
    if not (ui_dir / "index.html").exists():
        return v1_error(503, f"no UI build at {legacy.rel(ui_dir)} (cd frontend && npm run build, or set SIGIL_UI_DIR)")
    f = legacy.safe_join(ui_dir, path) if path else None
    return _file(f or ui_dir / "index.html")          # unknown paths -> index.html (SPA routing)
