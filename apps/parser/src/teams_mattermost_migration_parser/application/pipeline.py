"""Pipeline orchestration for end-to-end transformation runs."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ..config import ParserConfig
from ..domain.exceptions import ParserError
from ..observability.metrics import ParserMetrics
from .protocols import JsonlRecordWriter, TeamsExportSource
from .services import ExportValidationService, MattermostRecordService

LOGGER = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class PipelineResult:
    """Summary of a completed pipeline execution."""

    bytes_processed: int
    channels: int
    posts: int
    records_written: int
    teams: int
    users: int


class TransformationPipeline:
    """Coordinate source validation, record rendering, and JSONL output."""

    def __init__(
        self,
        *,
        config: ParserConfig,
        metrics: ParserMetrics,
        record_service: MattermostRecordService,
        source: TeamsExportSource,
        validator: ExportValidationService,
        writer: JsonlRecordWriter,
    ):
        self._config = config
        self._metrics = metrics
        self._record_service = record_service
        self._source = source
        self._validator = validator
        self._writer = writer

    def run(self) -> PipelineResult:
        start_time = time.perf_counter()
        bytes_processed = self._source.input_size_bytes()
        self._metrics.observe_input_bytes(bytes_processed)

        try:
            validation_result = self._time_stage(
                "validation",
                self._validator.validate,
                self._source,
            )
            records_written = self._time_stage("render_and_write", self._write_records)
            duration_seconds = time.perf_counter() - start_time
            self._metrics.mark_success(
                records_written=records_written,
                duration_seconds=duration_seconds,
            )
        except ParserError as exc:
            self._metrics.mark_failure(type(exc).__name__)
            LOGGER.exception(
                "pipeline execution failed",
                extra={"event": "pipeline_failed", "details": {"error": str(exc)}},
            )
            raise
        finally:
            self._writer.close()
            self._metrics.publish()

        LOGGER.info(
            "pipeline execution completed",
            extra={
                "event": "pipeline_completed",
                "details": {
                    "records_written": records_written,
                    "teams": validation_result.team_count,
                    "channels": validation_result.channel_count,
                    "users": validation_result.user_count,
                    "posts": validation_result.post_count,
                    "bytes_processed": bytes_processed,
                },
            },
        )
        return PipelineResult(
            bytes_processed=bytes_processed,
            channels=validation_result.channel_count,
            posts=validation_result.post_count,
            records_written=records_written,
            teams=validation_result.team_count,
            users=validation_result.user_count,
        )

    def _write_records(self) -> int:
        records_written = 0
        for record in self._record_service.iter_records(self._source):
            self._writer.write_record(record)
            self._metrics.observe_record(record["type"])
            records_written += 1
        self._writer.flush()
        return records_written

    def _time_stage(
        self,
        stage_name: str,
        func: Callable[..., ResultT],
        *args: object,
    ) -> ResultT:
        start_time = time.perf_counter()
        result = func(*args)
        self._metrics.observe_stage_duration(stage_name, time.perf_counter() - start_time)
        return result
