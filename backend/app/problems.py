"""Errors (API-10). v2 answers RFC 9457 `application/problem+json`; v1 keeps its `{"error": "..."}` bodies."""
from __future__ import annotations

import json
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_TYPE = "application/problem+json"
V2_PREFIX = "/api/v2"


class BodyTooLarge(Exception):
    """Raised by the security middleware's capped receive() when a body exceeds its limit."""


class Problem(BaseModel):
    """RFC 9457 problem details. Extension members (e.g. `problems`, `errors`, `job`) may be present."""
    model_config = ConfigDict(extra="allow")
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class ProblemError(Exception):
    def __init__(self, status: int, detail: str | None = None, title: str | None = None, type_: str = "about:blank",
                 headers: dict | None = None, **extensions):
        self.status, self.detail, self.type = status, detail, type_
        self.title = title or HTTPStatus(status).phrase
        self.headers, self.extensions = headers or {}, extensions


def problem_response(request: Request | None, status: int, detail: str | None = None, title: str | None = None,
                     type_: str = "about:blank", headers: dict | None = None, **ext) -> Response:
    body = {"type": type_, "title": title or HTTPStatus(status).phrase, "status": status}
    if detail:
        body["detail"] = detail
    if request is not None:
        body["instance"] = request.url.path
    body.update(ext)
    return Response(json.dumps(body), status_code=status, media_type=PROBLEM_TYPE,
                    headers={"Cache-Control": "no-store", **(headers or {})})


class LegacyJSONResponse(JSONResponse):
    """v1 bodies exactly as demo/server.py's json.dumps (it tolerates NaN in result files)."""
    def render(self, content) -> bytes:
        return json.dumps(content).encode()


def v1_json(obj, status: int = 200) -> Response:
    return LegacyJSONResponse(obj, status_code=status, headers={"Cache-Control": "no-store"})


def v1_error(status: int, message: str, **extra) -> Response:
    return v1_json({"error": message, **extra}, status)


def is_v2(path: str) -> bool:
    return path == V2_PREFIX or path.startswith(V2_PREFIX + "/")


def install(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError):
        if not is_v2(request.url.path):
            return v1_error(exc.status, exc.detail or exc.title, **exc.extensions)
        return problem_response(request, exc.status, exc.detail, exc.title, exc.type, exc.headers, **exc.extensions)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if isinstance(exc.__cause__, BodyTooLarge):        # raised while FastAPI parsed a form body
            exc = StarletteHTTPException(413, "request body too large")
        if is_v2(request.url.path):
            detail = exc.detail if isinstance(exc.detail, str) and exc.detail != HTTPStatus(exc.status_code).phrase else None
            return problem_response(request, exc.status_code, detail, headers=getattr(exc, "headers", None))
        status = 404 if exc.status_code == 405 else exc.status_code     # v1: unknown method+path is "not found"
        return v1_error(status, "not found" if status == 404 else str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
                  for e in exc.errors()]
        if is_v2(request.url.path):
            return problem_response(request, 422, "the request is invalid", "Unprocessable Content", errors=errors)
        return v1_error(400, "; ".join(f"{'.'.join(e['loc'])}: {e['msg']}" for e in errors) or "bad request")

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        import logging
        logging.getLogger("sigil.backend").exception("unhandled error on %s %s", request.method, request.url.path)
        if is_v2(request.url.path):
            return problem_response(request, 500, "internal server error")
        return v1_error(500, "internal server error")


# OpenAPI: the error responses every v2 endpoint may give
def responses(*codes: int) -> dict:
    desc = {400: "Bad request", 401: "Missing or invalid bearer token", 403: "Forbidden (role, host or origin)",
            404: "Not found", 409: "Conflict", 413: "Payload too large", 415: "Unsupported media type",
            422: "Validation failed (details in `errors` / `problems`)", 503: "Service unavailable"}
    return {c: {"model": Problem, "description": desc.get(c, HTTPStatus(c).phrase),
                "content": {PROBLEM_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}}} for c in codes}
