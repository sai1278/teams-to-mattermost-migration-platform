"""Backward-compatible logging exports."""

from __future__ import annotations

from .observability.logging import configure_logging

__all__ = ["configure_logging"]
