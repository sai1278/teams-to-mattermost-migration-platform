"""Structured logging configuration for CLI execution."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from .context import correlation_id_var


class CorrelationContextFilter(logging.Filter):
    """Inject execution context into every log record."""

    def __init__(self, service_name: str):
        super().__init__()
        self._service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        record.service_name = self._service_name
        return True


class JsonLogFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": getattr(record, "service_name", "unknown"),
            "correlation_id": getattr(record, "correlation_id", "unknown"),
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "details"):
            payload["details"] = record.details
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str, *, service_name: str) -> None:
    """Install a JSON logger suitable for automation pipelines."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(CorrelationContextFilter(service_name))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
