"""Request-like execution context for CLI correlation IDs."""

from __future__ import annotations

from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="unknown")


def set_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID to the current execution context."""

    correlation_id_var.set(correlation_id)
