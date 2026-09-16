"""Structured logging.

JSON by default so logs are queryable in aggregate. Two rules that matter more
than the format:

  1. A request id is attached to every log line and to every audit row written
     during that request, so a support question ("why was this unit blocked?")
     is answerable from either side.

  2. PII never reaches the logs. A redaction filter strips known-sensitive keys
     even when a caller passes them by mistake - relying on every log call site
     to remember would be a matter of time.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.config import get_settings

#: Correlates log lines, audit rows, and job runs for one request.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
actor_id_ctx: ContextVar[str | None] = ContextVar("actor_id", default=None)

#: Keys whose values are replaced before a record is emitted. Matched
#: case-insensitively against the end of the key, so `stnk_nama_pemilik` is
#: caught as well as `nama_pemilik`.
REDACT_KEY_SUFFIXES: tuple[str, ...] = (
    "nama_pemilik",
    "alamat",
    "nik",
    "nomor_bpkb",
    "password",
    "password_hash",
    "token",
    "token_hash",
    "refresh_token",
    "access_token",
    "authorization",
    "api_key",
    "secret",
    "jwt_secret",
    "pii_encryption_keys",
)

REDACTED = "[REDACTED]"


def _should_redact(key: str) -> bool:
    lowered = key.lower()
    return any(lowered.endswith(suffix) for suffix in REDACT_KEY_SUFFIXES)


def redact_pii(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    def scrub(value: Any, depth: int = 0) -> Any:
        if depth > 6:
            return value
        if isinstance(value, dict):
            return {k: (REDACTED if _should_redact(k) else scrub(v, depth + 1)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [scrub(v, depth + 1) for v in value]
        return value

    return {k: (REDACTED if _should_redact(k) else scrub(v)) for k, v in event_dict.items()}


def add_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    if (rid := request_id_ctx.get()) is not None:
        event_dict.setdefault("request_id", rid)
    if (aid := actor_id_ctx.get()) is not None:
        event_dict.setdefault("actor_id", aid)
    return event_dict


def configure_logging() -> None:
    settings = get_settings()

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        add_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Redaction runs last among the enrichers so it also covers keys added
        # by the processors above.
        redact_pii,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, sqlalchemy, rq) through the same pipeline
    # so the output is one consistent stream rather than two interleaved ones.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
