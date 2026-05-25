"""Dependency wiring for the parser application."""

from __future__ import annotations

from .application.pipeline import TransformationPipeline
from .application.services import ExportValidationService, MattermostRecordService
from .config import ParserConfig
from .infrastructure.readers import TeamsExportFileGateway
from .infrastructure.writers import JsonlFileWriter
from .observability.metrics import ParserMetrics


def build_pipeline(config: ParserConfig) -> TransformationPipeline:
    """Build the default pipeline graph for CLI execution."""

    source = TeamsExportFileGateway(config.input_path)
    writer = JsonlFileWriter(config.output_path, batch_size=config.batch_size)

    return TransformationPipeline(
        config=config,
        metrics=ParserMetrics(config),
        record_service=MattermostRecordService(config),
        source=source,
        validator=ExportValidationService(config),
        writer=writer,
    )
