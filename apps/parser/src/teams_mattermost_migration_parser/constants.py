"""Shared constants for parser defaults and record types."""

from __future__ import annotations

from typing import Final

DEFAULT_BATCH_SIZE: Final[int] = 500
DEFAULT_DEFAULT_PASSWORD: Final[str] = "TemporarySecurePassword123!"
DEFAULT_METRICS_OUTPUT_PATH: Final[str] = "artifacts/metrics/parser.prom"
DEFAULT_OTEL_SERVICE_NAME: Final[str] = "teams-mattermost-migration-parser"

RECORD_TYPE_VERSION: Final[str] = "version"
RECORD_TYPE_TEAM: Final[str] = "team"
RECORD_TYPE_CHANNEL: Final[str] = "channel"
RECORD_TYPE_USER: Final[str] = "user"
RECORD_TYPE_POST: Final[str] = "post"

SCRUB_KEYWORDS: Final[tuple[str, ...]] = ("confidential", "secret", "restricted")
