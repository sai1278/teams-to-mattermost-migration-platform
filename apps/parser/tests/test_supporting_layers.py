from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, NoReturn

import pytest

from teams_mattermost_migration_parser import cli, logging_utils
from teams_mattermost_migration_parser import transformer as transformer_module
from teams_mattermost_migration_parser.application.pipeline import (
    PipelineResult,
    TransformationPipeline,
)
from teams_mattermost_migration_parser.application.services import (
    ExportValidationService,
    MattermostRecordService,
)
from teams_mattermost_migration_parser.config import ParserConfig
from teams_mattermost_migration_parser.container import build_pipeline
from teams_mattermost_migration_parser.domain.exceptions import (
    InputValidationError,
    SourceReadError,
)
from teams_mattermost_migration_parser.domain.models import (
    DirectChannelRecord,
    TeamRecord,
    TeamsExport,
    UserRecord,
)
from teams_mattermost_migration_parser.domain.normalization import (
    AnonymizerPipeline,
    scrub_message,
)
from teams_mattermost_migration_parser.infrastructure.readers import TeamsExportFileGateway
from teams_mattermost_migration_parser.infrastructure.writers import JsonlFileWriter
from teams_mattermost_migration_parser.observability.context import set_correlation_id
from teams_mattermost_migration_parser.observability.metrics import ParserMetrics
from teams_mattermost_migration_parser.transformer import TeamsExportTransformer


def _config(tmp_path: Path, **overrides: Any) -> ParserConfig:
    return ParserConfig.from_inputs(
        input_path=tmp_path / "source" / "input.json",
        output_path=tmp_path / "output" / "import.jsonl",
        metrics_output_path=tmp_path / "metrics" / "parser.prom",
        **overrides,
    )


def test_cli_main_builds_config_and_delegates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "source" / "input.json"
    output_path = tmp_path / "output" / "import.jsonl"
    metrics_path = tmp_path / "metrics" / "parser.prom"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text("{}", encoding="utf-8")

    captured: dict[str, ParserConfig] = {}

    class _FakePipeline:
        def run(self) -> PipelineResult:
            return PipelineResult(
                bytes_processed=1,
                channels=2,
                posts=3,
                records_written=4,
                teams=5,
                users=6,
            )

    def fake_build_pipeline(config: ParserConfig) -> _FakePipeline:
        captured["config"] = config
        return _FakePipeline()

    monkeypatch.setattr(cli, "build_pipeline", fake_build_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "teams-mattermost-migration-parser",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--metrics-output",
            str(metrics_path),
        ],
    )

    assert cli.main() == 0
    assert captured["config"].input_path == input_path
    assert captured["config"].output_path == output_path
    assert captured["config"].default_password.get_secret_value() == ""
    assert captured["config"].metrics_output_path == metrics_path


def test_transformer_run_delegates_to_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)

    class _FakePipeline:
        def run(self) -> PipelineResult:
            return PipelineResult(
                bytes_processed=10,
                channels=1,
                posts=2,
                records_written=3,
                teams=4,
                users=5,
            )

    monkeypatch.setattr(
        "teams_mattermost_migration_parser.transformer.build_pipeline",
        lambda _config: _FakePipeline(),
    )

    result = TeamsExportTransformer(config).run()

    assert result.records_written == 3
    assert result.teams == 4
    assert result.posts == 2


def test_in_memory_source_helpers_expose_export() -> None:
    export = TeamsExport(teams=(), users=(), direct_channels=())
    source = transformer_module._InMemorySource(export)

    assert source.input_size_bytes() == 0
    assert source.materialize() is export


def test_file_gateway_streams_and_reports_errors(tmp_path: Path) -> None:
    fixture = (
        Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample-teams-export.json"
    )
    gateway = TeamsExportFileGateway(fixture)
    export = gateway.materialize()

    assert gateway.input_size_bytes() > 0
    assert len(export.teams) == 2
    assert len(export.users) == 3
    assert len(list(gateway.iter_teams())) == 2
    assert len(list(gateway.iter_users())) == 3
    assert len(list(gateway.iter_direct_channels())) == 0

    missing_gateway = TeamsExportFileGateway(tmp_path / "missing.json")
    with pytest.raises(SourceReadError):
        missing_gateway.input_size_bytes()

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SourceReadError):
        list(TeamsExportFileGateway(bad_json).iter_users())

    malformed = tmp_path / "malformed.json"
    malformed.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "broken-user",
                        "nickname": "Broken",
                        "teams": [],
                    }
                ],
                "teams": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InputValidationError):
        list(TeamsExportFileGateway(malformed).iter_users())

    with pytest.raises(SourceReadError):
        list(TeamsExportFileGateway(tmp_path).iter_users())


def test_jsonl_writer_batches_and_appends(tmp_path: Path) -> None:
    output_path = tmp_path / "output.jsonl"

    writer = JsonlFileWriter(output_path, batch_size=1)
    writer.write_record({"type": "version", "version": 1})
    writer.close()

    assert writer.append_mode is False
    assert writer.has_existing_content is False
    assert [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()] == [
        {"type": "version", "version": 1}
    ]

    appender = JsonlFileWriter(output_path, batch_size=1, append=True)
    appender.write_record({"type": "team", "team": {"name": "it-team"}})
    appender.close()

    assert appender.append_mode is True
    assert appender.has_existing_content is True
    rendered = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rendered[0]["type"] == "version"
    assert rendered[1]["type"] == "team"


def test_structured_logging_wrapper_emits_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging_utils.configure_logging("INFO", service_name="parser-test")
    set_correlation_id("corr-123")

    logger = logging.getLogger("parser.test")
    logger.info("hello world", extra={"event": "demo", "details": {"team": "it"}})

    rendered = capsys.readouterr().out.strip().splitlines()
    payload = json.loads(rendered[-1])

    assert payload["service"] == "parser-test"
    assert payload["correlation_id"] == "corr-123"
    assert payload["event"] == "demo"
    assert payload["details"] == {"team": "it"}


def test_anonymization_shortcuts_cover_empty_and_keyword_paths() -> None:
    assert AnonymizerPipeline().anonymize("") == ""
    assert scrub_message("confidential document") == "[PII SCRUBBED]"


def test_container_build_pipeline_uses_checkpoint_append_mode(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    assert config.checkpoint_path is not None
    config.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    config.checkpoint_path.write_text("{}", encoding="utf-8")

    pipeline = build_pipeline(config)

    assert getattr(pipeline._writer, "append_mode", False) is True


class _FailingValidator(ExportValidationService):
    def __init__(self, config: ParserConfig) -> None:
        super().__init__(config)

    def validate(self, _source: Any) -> NoReturn:
        raise InputValidationError("validation failed")


class _FailureWriter:
    def __init__(self) -> None:
        self.closed = False

    def write_record(self, _record: Mapping[str, Any]) -> None:
        raise AssertionError("writer should not be called")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _MinimalSource:
    def __init__(self, export: TeamsExport) -> None:
        self._export = export

    def iter_teams(self) -> Iterator[TeamRecord]:
        return iter(self._export.teams)

    def iter_users(self) -> Iterator[UserRecord]:
        return iter(self._export.users)

    def iter_direct_channels(self) -> Iterator[DirectChannelRecord]:
        return iter(self._export.direct_channels)

    def input_size_bytes(self) -> int:
        return 42

    def materialize(self) -> TeamsExport:
        return self._export


def test_pipeline_failure_marks_metrics_and_closes_writer(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=False)
    metrics = ParserMetrics(config)
    writer = _FailureWriter()
    export = TeamsExport(
        teams=(
            TeamRecord(
                name="it-team",
                display_name="IT Team",
            ),
        ),
        users=(),
        direct_channels=(),
    )
    pipeline = TransformationPipeline(
        config=config,
        metrics=metrics,
        record_service=MattermostRecordService(config, metrics=metrics),
        source=_MinimalSource(export),
        validator=_FailingValidator(config),
        writer=writer,
    )

    with pytest.raises(InputValidationError):
        pipeline.run()

    assert writer.closed is True
    assert config.metrics_output_path is not None
    rendered = config.metrics_output_path.read_text(encoding="utf-8")
    assert 'tmmp_parser_failures_total{error_type="InputValidationError"} 1.0' in rendered
