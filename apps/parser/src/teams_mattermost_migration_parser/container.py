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

    resume_append = False
    if config.resume and config.checkpoint_path and config.checkpoint_path.exists():
        resume_append = True

    metrics = ParserMetrics(config)
    writer = JsonlFileWriter(
        config.output_path,
        batch_size=config.batch_size,
        append=resume_append,
        max_chunk_mb=config.max_chunk_mb
    )

    return TransformationPipeline(
        config=config,
        metrics=metrics,
        record_service=MattermostRecordService(config, metrics=metrics),
        source=source,
        validator=ExportValidationService(config),
        writer=writer,
    )
