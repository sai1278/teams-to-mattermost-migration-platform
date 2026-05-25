"""Backward-compatible transformation helpers built on the layered pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from os import PathLike
from typing import Any

from .application.pipeline import PipelineResult
from .application.services import MattermostRecordService
from .config import ParserConfig
from .container import build_pipeline
from .domain.models import TeamRecord, TeamsExport, UserRecord
from .infrastructure.readers import TeamsExportFileGateway
from .infrastructure.writers import JsonlFileWriter


def load_export(input_path: str | PathLike[str]) -> TeamsExport:
    """Materialize the export file for callers that still expect an aggregate object."""

    return TeamsExportFileGateway(input_path).materialize()


class TeamsExportTransformer:
    """Compatibility wrapper around the record rendering service."""

    def __init__(self, config: ParserConfig):
        self._config = config
        self._record_service = MattermostRecordService(config)

    def render_records(self, export: TeamsExport) -> list[dict[str, Any]]:
        return list(self._record_service.iter_records(_InMemorySource(export)))

    def write_records(self, export: TeamsExport) -> int:
        self._config.ensure_output_parent()
        writer = JsonlFileWriter(self._config.output_path, batch_size=self._config.batch_size)
        records_written = 0
        try:
            for record in self.render_records(export):
                writer.write_record(record)
                records_written += 1
            writer.flush()
            return records_written
        finally:
            writer.close()

    def run(self) -> PipelineResult:
        """Execute the full pipeline against the configured input file."""

        return build_pipeline(self._config).run()


class _InMemorySource:
    """Minimal source adapter used by compatibility helpers and unit tests."""

    def __init__(self, export: TeamsExport):
        self._export = export

    def iter_teams(self) -> Iterator[TeamRecord]:
        return iter(self._export.teams)

    def iter_users(self) -> Iterator[UserRecord]:
        return iter(self._export.users)

    def input_size_bytes(self) -> int:
        return 0

    def materialize(self) -> TeamsExport:
        return self._export
