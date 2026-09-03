"""Structured JSON logging with secret redaction (§48)."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
run_id_ctx: ContextVar[str | None] = ContextVar("run_id", default=None)
agent_run_id_ctx: ContextVar[str | None] = ContextVar("agent_run_id", default=None)

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9\-_]{8,})"),
    re.compile(r"(AIza[0-9A-Za-z\-_]{8,})"),
    re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^\s\"']+)"),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([^\s\",}]+)"),
]


def redact(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(
            lambda m: (
                (m.group(1) + "***REDACTED***")
                if m.lastindex and m.lastindex > 1
                else "***REDACTED***"
            ),
            out,
        )
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, ctx in (
            ("request_id", request_id_ctx),
            ("run_id", run_id_ctx),
            ("agent_run_id", agent_run_id_ctx),
        ):
            val = ctx.get()
            if val:
                payload[key] = val
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    for noisy in ("uvicorn.access", "httpx", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
