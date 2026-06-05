"""Protocols used to isolate application logic from infrastructure details."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Protocol

from ..domain.models import DirectChannelRecord, TeamRecord, TeamsExport, UserRecord


class TeamsExportSource(Protocol):
    """Abstraction for reading normalized Teams export data."""

    def iter_teams(self) -> Iterator[TeamRecord]:
        """Yield team records from the export source."""

    def iter_users(self) -> Iterator[UserRecord]:
        """Yield user records from the export source."""

    def iter_direct_channels(self) -> Iterator[DirectChannelRecord]:
        """Yield direct message channel records from the export source."""

    def input_size_bytes(self) -> int:
        """Return the raw size of the input payload in bytes."""

    def materialize(self) -> TeamsExport:
        """Materialize the full export when a caller explicitly needs it."""


class JsonlRecordWriter(Protocol):
    """Abstraction for persisting Mattermost JSONL records."""

    def write_record(self, record: Mapping[str, Any]) -> None:
        """Persist a single JSONL record."""

    def flush(self) -> None:
        """Flush any buffered records to durable storage."""

    def close(self) -> None:
        """Release writer resources."""
