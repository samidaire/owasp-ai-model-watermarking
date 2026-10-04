"""Security middleware (API-01): the posture of UI_INTEGRATION.md §10, as one pure ASGI layer.

  * Host check:   every request's Host must be localhost / 127.0.0.1 / [::1] with a digits-only port
                  (403), which blocks DNS rebinding. Parsing is demo/server.py's host_of.
  * Origin check: state-changing requests (POST, PUT, PATCH, DELETE) with a foreign Origin get 403, so
                  other websites can't trigger anything.
  * JSON only:    state-changing requests must be `Content-Type: application/json` (415). The two upload
                  endpoints also accept multipart/form-data; they require a bearer token, which a cross-site
                  form can't send.
  * Body limits:  64 KiB for v1, SIGIL_MAX_JSON_BYTES for v2 JSON, SIGIL_MAX_UPLOAD_BYTES for uploads (413).
  * CORS:         answered only for localhost origins (never `*`), including the preflight.
  * Headers:      nosniff, no framing, no referrer; JSON is never cached.
It also writes the structured request log (method, path without query string, status, duration).
"""
from __future__ import annotations

import json
import re
import time

from . import legacy
from .logs import access
from .problems import PROBLEM_TYPE, BodyTooLarge, is_v2

STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
# (method, path regex) that also accept multipart/form-data uploads
MULTIPART_ENDPOINTS = [("POST", re.compile(r"^/api/v2/models/?$")),
                       ("POST", re.compile(r"^/api/v2/claims/[0-9]+/proofs/upload/?$"))]
SECURITY_HEADERS = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer")]


def host_allowed(raw_hosts: list[bytes]) -> bool:
    if not raw_hosts:
        return True                         # HTTP/1.0 client without a Host header (as demo/server.py)
    if len(raw_hosts) != 1:
        return False
    return legacy.host_of(raw_hosts[0].decode("latin-1")) in legacy.LOCAL_HOSTS


def origin_allowed(origin: str | None) -> bool:
    return bool(origin) and legacy.origin_allowed(origin)


class SecurityMiddleware:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    # ------------------------------------------------------------------ helpers
    @staticmethod
    async def _send_error(send, path: str, status: int, message: str, extra_headers=()):
        if is_v2(path):
            body = json.dumps({"type": "about:blank", "title": message, "status": status, "detail": message,
                               "instance": path}).encode()
            ctype = PROBLEM_TYPE.encode()
        else:
            body, ctype = json.dumps({"error": message}).encode(), b"application/json"
        headers = [(b"content-type", ctype), (b"content-length", str(len(body)).encode()),
                   (b"cache-control", b"no-store"), *SECURITY_HEADERS, *extra_headers]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _limit(self, method: str, path: str, multipart: bool) -> int:
        if multipart:
            return self.settings.max_upload_bytes + 1024 * 1024
        if is_v2(path):
            return self.settings.max_json_bytes
        return legacy.MAX_BODY

    # ------------------------------------------------------------------ ASGI
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        t0 = time.perf_counter()
        method, path = scope["method"], scope["path"]
        headers = {}
        hosts = []
        for k, v in scope.get("headers", []):
            if k == b"host":
                hosts.append(v)
            headers.setdefault(k.decode("latin-1").lower(), v.decode("latin-1"))
        origin = headers.get("origin")
        cors = [(b"access-control-allow-origin", origin.encode("latin-1")), (b"vary", b"Origin")] \
            if origin_allowed(origin) else []
        status_box = {"status": 0}

        def done(status):
            access.info("%s %s %s", method, path, status,
                        extra={"method": method, "path": path, "status": status,
                               "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})

        host_ok = host_allowed(hosts)
        if method == "OPTIONS":
            if not host_ok or not origin_allowed(origin):
                await self._send_error(send, path, 403, "origin not allowed")
                return done(403)
            headers_out = [*cors, (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
                           (b"access-control-allow-headers", b"Content-Type, Last-Event-ID, Authorization"),
                           (b"access-control-max-age", b"600"), (b"content-length", b"0")]
            await send({"type": "http.response.start", "status": 204, "headers": headers_out})
            await send({"type": "http.response.body", "body": b""})
            return done(204)

        multipart = False
        if method in STATE_CHANGING:
            if not host_ok or (origin is not None and not origin_allowed(origin)):
                await self._send_error(send, path, 403, "origin not allowed", cors)
                return done(403)
            ctype = headers.get("content-type", "").lower()
            multipart = ctype.startswith("multipart/form-data") and any(
                m == method and rx.match(path) for m, rx in MULTIPART_ENDPOINTS)
            has_body = "content-length" in headers and headers["content-length"].strip() not in ("", "0") \
                or "transfer-encoding" in headers
            if not (ctype.startswith("application/json") or multipart) and (method != "DELETE" or has_body):
                await self._send_error(send, path, 415, "Content-Type must be application/json", cors)
                return done(415)
            raw_len = headers.get("content-length")
            if raw_len is not None:
                try:
                    n = int(raw_len)
                except ValueError:
                    n = -1
                if n < 0:
                    await self._send_error(send, path, 400, "bad Content-Length", cors)
                    return done(400)
                if n > self._limit(method, path, multipart):
                    await self._send_error(send, path, 413, "request body too large", cors)
                    return done(413)
        elif not host_ok:
            await self._send_error(send, path, 403, "host not allowed")
            return done(403)

        limit = self._limit(method, path, multipart)
        received = {"n": 0}

        async def capped_receive():
            message = await receive()
            if message["type"] == "http.request":
                received["n"] += len(message.get("body", b""))
                if received["n"] > limit:
                    raise BodyTooLarge()
            return message

        started = {"v": False}

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                started["v"] = True
                status_box["status"] = message["status"]
                hdrs = list(message.get("headers", []))
                names = {k.lower() for k, _ in hdrs}
                hdrs += [h for h in SECURITY_HEADERS if h[0] not in names]
                hdrs += [h for h in cors if h[0] not in names]
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, capped_receive, wrapped_send)
        except BodyTooLarge:
            if not started["v"]:
                await self._send_error(send, path, 413, "request body too large", cors)
                status_box["status"] = 413
        done(status_box["status"])
