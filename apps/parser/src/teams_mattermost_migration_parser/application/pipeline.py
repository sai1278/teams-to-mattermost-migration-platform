"""Pipeline orchestration for end-to-end transformation runs."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from ..config import ParserConfig
from ..constants import (
    RECORD_TYPE_CHANNEL,
    RECORD_TYPE_POST,
    RECORD_TYPE_TEAM,
    RECORD_TYPE_USER,
    RECORD_TYPE_VERSION,
)
from ..domain.exceptions import ParserError
from ..observability.metrics import ParserMetrics
from .protocols import JsonlRecordWriter, TeamsExportSource
from .services import ExportValidationService, MattermostRecordService

LOGGER = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")


class MigrationCheckpoint:
    """Handles loading, saving, and deleting migration checkpoints for crash-resume support."""

    def __init__(self, path: Path):
        self.path = path
        self.completed_teams: set[str] = set()
        self.completed_channels: set[str] = set()  # format: team_slug/channel_slug
        self.completed_users: set[str] = set()
        self.completed_direct_channels: set[str] = set()  # format: comma-sorted members
        self.last_post_timestamp: int = 0
        self.last_direct_post_timestamp: int = 0
        self.stats: dict[str, int] = {}

    @classmethod
    def load(cls, path: Path) -> MigrationCheckpoint | None:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            checkpoint = cls(path)
            checkpoint.completed_teams = set(data.get("completed_teams", []))
            checkpoint.completed_channels = set(data.get("completed_channels", []))
            checkpoint.completed_users = set(data.get("completed_users", []))
            checkpoint.completed_direct_channels = set(data.get("completed_direct_channels", []))
            checkpoint.last_post_timestamp = data.get("last_post_timestamp", 0)
            checkpoint.last_direct_post_timestamp = data.get("last_direct_post_timestamp", 0)
            checkpoint.stats = data.get("stats", {})
            return checkpoint
        except Exception as exc:
            LOGGER.warning(f"Failed to load checkpoint file {path}: {exc}")
            return None

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "completed_teams": list(self.completed_teams),
                "completed_channels": list(self.completed_channels),
                "completed_users": list(self.completed_users),
                "completed_direct_channels": list(self.completed_direct_channels),
                "last_post_timestamp": self.last_post_timestamp,
                "last_direct_post_timestamp": self.last_direct_post_timestamp,
                "stats": self.stats,
            }
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            LOGGER.error(f"Failed to save checkpoint: {exc}")

    def delete(self) -> None:
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError as exc:
                LOGGER.warning(f"Failed to delete checkpoint file {self.path}: {exc}")


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

        checkpoint = None
        resume_mode = False
        if self._config.resume and self._config.checkpoint_path:
            loaded_checkpoint = MigrationCheckpoint.load(self._config.checkpoint_path)
            if loaded_checkpoint is not None:
                checkpoint = loaded_checkpoint
                if getattr(self._writer, "has_existing_content", False):
                    resume_mode = True
                    self._metrics.observe_checkpoint_resume()
                else:
                    LOGGER.warning(
                        "checkpoint found but output file has no existing content; starting fresh",
                        extra={
                            "event": "resume_reset",
                            "details": {"checkpoint_path": str(self._config.checkpoint_path)},
                        },
                    )
                    checkpoint = MigrationCheckpoint(self._config.checkpoint_path)
            else:
                checkpoint = MigrationCheckpoint(self._config.checkpoint_path)

        try:
            validation_result = self._time_stage(
                "validation",
                self._validator.validate,
                self._source,
            )
            records_written = self._time_stage(
                "render_and_write", self._write_records, checkpoint, resume_mode
            )
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
        else:
            if checkpoint:
                checkpoint.delete()
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

    def _write_records(self, checkpoint: MigrationCheckpoint | None, resume_mode: bool) -> int:
        records_written = 0
        for record in self._record_service.iter_records(self._source):
            rec_type = record["type"]

            # Resuming check
            if checkpoint and resume_mode:
                if rec_type == RECORD_TYPE_VERSION:
                    # Version record is always written first in a resumed file when the output
                    # already contains prior content.
                    continue
                elif rec_type == RECORD_TYPE_TEAM:
                    t_name = record["team"]["name"]
                    if t_name in checkpoint.completed_teams:
                        continue
                elif rec_type == RECORD_TYPE_CHANNEL:
                    chan_key = f"{record['channel']['team']}/{record['channel']['name']}"
                    if chan_key in checkpoint.completed_channels:
                        continue
                elif rec_type == RECORD_TYPE_USER:
                    u_name = record["user"]["username"]
                    if u_name in checkpoint.completed_users:
                        continue
                elif rec_type == RECORD_TYPE_POST:
                    post = record["post"]
                    chan_key = f"{post['team']}/{post['channel']}"
                    if chan_key in checkpoint.completed_channels:
                        continue
                    if post["create_at"] <= checkpoint.last_post_timestamp:
                        continue
                elif rec_type == "direct_channel":
                    members_key = ",".join(sorted(record["direct_channel"]["members"]))
                    if members_key in checkpoint.completed_direct_channels:
                        continue
                elif rec_type == "direct_post":
                    dpost = record["direct_post"]
                    members_key = ",".join(sorted(dpost["channel_members"]))
                    if members_key in checkpoint.completed_direct_channels:
                        continue
                    if dpost["create_at"] <= checkpoint.last_direct_post_timestamp:
                        continue

            self._writer.write_record(record)
            self._metrics.observe_record(rec_type)
            records_written += 1

            # Update checkpoint state
            if checkpoint:
                if rec_type == RECORD_TYPE_TEAM:
                    checkpoint.completed_teams.add(record["team"]["name"])
                elif rec_type == RECORD_TYPE_CHANNEL:
                    chan_key = f"{record['channel']['team']}/{record['channel']['name']}"
                    checkpoint.completed_channels.add(chan_key)
                elif rec_type == RECORD_TYPE_USER:
                    checkpoint.completed_users.add(record["user"]["username"])
                elif rec_type == RECORD_TYPE_POST:
                    checkpoint.last_post_timestamp = max(
                        checkpoint.last_post_timestamp, record["post"]["create_at"]
                    )
                elif rec_type == "direct_channel":
                    members_key = ",".join(sorted(record["direct_channel"]["members"]))
                    checkpoint.completed_direct_channels.add(members_key)
                elif rec_type == "direct_post":
                    checkpoint.last_direct_post_timestamp = max(
                        checkpoint.last_direct_post_timestamp, record["direct_post"]["create_at"]
                    )

                checkpoint.stats[rec_type] = checkpoint.stats.get(rec_type, 0) + 1
                if records_written % self._config.batch_size == 0:
                    checkpoint.save()

        self._writer.flush()
        if checkpoint:
            checkpoint.save()
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
