from __future__ import annotations

from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from teams_mattermost_migration_parser.application.pipeline import (
    TransformationPipeline,
)
from teams_mattermost_migration_parser.application.services import (
    ExportValidationService,
    MattermostRecordService,
)
from teams_mattermost_migration_parser.config import ParserConfig
from teams_mattermost_migration_parser.domain.models import (
    TeamsExport,
)
from teams_mattermost_migration_parser.observability.metrics import ParserMetrics


class _InMemorySource:
    def __init__(self, export: TeamsExport) -> None:
        self._export = export

    def iter_teams(self) -> any:
        return iter(self._export.teams)

    def iter_users(self) -> any:
        return iter(self._export.users)

    def iter_direct_channels(self) -> any:
        return iter(self._export.direct_channels)

    def input_size_bytes(self) -> int:
        return 100

    def validate_schema_version(self) -> None:
        pass


class _InMemoryWriter:
    def __init__(self) -> None:
        self.records = []

    def write_record(self, record) -> None:
        self.records.append(record)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_opentelemetry_pipeline_spans(tmp_path: Path) -> None:
    # Set up InMemorySpanExporter
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    
    orig_provider = getattr(trace, "_TRACER_PROVIDER", None)
    trace._TRACER_PROVIDER = provider

    try:
        # Setup pipeline
        config = ParserConfig.from_inputs(
            input_path=tmp_path / "input.json",
            output_path=tmp_path / "output.jsonl",
            correlation_id="test-correlation-123",
            fail_on_empty_export=False,
        )
        metrics = ParserMetrics(config)
        record_service = MattermostRecordService(config)
        validator = ExportValidationService(config)
        source = _InMemorySource(TeamsExport(users=(), teams=(), direct_channels=()))
        writer = _InMemoryWriter()

        pipeline = TransformationPipeline(
            config=config,
            metrics=metrics,
            record_service=record_service,
            source=source,
            validator=validator,
            writer=writer,
        )

        # Run the pipeline
        pipeline.run()
    finally:
        if orig_provider is not None:
            trace._TRACER_PROVIDER = orig_provider

    # Retrieve and verify spans
    spans = exporter.get_finished_spans()
    
    # We expect spans: schema_version_check, validation,
    # render_and_write, and migration_pipeline_run (parent)
    span_names = {span.name for span in spans}
    assert "migration_pipeline_run" in span_names
    assert "schema_version_check" in span_names
    assert "validation" in span_names
    assert "render_and_write" in span_names

    # Check root span attributes
    root_span = next(span for span in spans if span.name == "migration_pipeline_run")
    assert root_span.attributes["correlation_id"] == "test-correlation-123"
    assert root_span.attributes["bytes_processed"] == 100
    assert root_span.status.is_ok
