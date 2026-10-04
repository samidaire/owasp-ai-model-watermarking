"""Structured logging without secrets (API-10).

Every record is one JSON object per line. A redaction pass runs over the message, the exception text and
every extra field, so a token, password, passphrase, seed or private key that slips into a log call is
masked before it is written. Request bodies are never logged; request paths are logged without query strings.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time

REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[redacted private key]"),
    (re.compile(r"\bsgl_[A-Za-z0-9_\-]{8,}"), "sgl_[redacted]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]+"), "Bearer [redacted]"),
    (re.compile(r"\$argon2(?:id|i|d)\$[^\s\"']+"), "$argon2id$[redacted]"),
    (re.compile(r"(?i)([\"']?\b(?:password|passphrase|secret|seed|token|private_key|authorization)[\"']?\s*[:=]\s*)"
                r"(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"), r"\1[redacted]"),
]
EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "client", "job_id", "step", "user", "action", "event")


def redact(text: str) -> str:
    for pattern, repl in REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
               "level": record.levelname, "logger": record.name, "msg": redact(record.getMessage())}
        for k in EXTRA_FIELDS:
            if hasattr(record, k):
                v = getattr(record, k)
                out[k] = redact(v) if isinstance(v, str) else v
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, ensure_ascii=False, default=str)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactFilter(logging.Filter):
    """Also attached to handlers we don't own (e.g. a test's caplog)."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = redact(record.getMessage()), ()
        return True


_HANDLER: logging.Handler | None = None


def configure(level: str = "INFO", as_json: bool = True, stream=None) -> logging.Handler:
    """Route the app's and uvicorn's loggers through one redacting handler. Idempotent."""
    global _HANDLER
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if as_json else PlainFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactFilter())
    for name in ("sigil", "uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        if _HANDLER in lg.handlers:
            lg.removeHandler(_HANDLER)
        lg.handlers = [h for h in lg.handlers if not isinstance(h, logging.StreamHandler)] + [handler]
        lg.setLevel(level.upper())
        lg.propagate = False
    logging.getLogger("uvicorn.access").disabled = True     # replaced by our request log (no query strings)
    _HANDLER = handler
    return handler


log = logging.getLogger("sigil.backend")
access = logging.getLogger("sigil.access")
