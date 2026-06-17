"""Pipeline orchestration for end-to-end transformation runs."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import tempfile
import time
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from opentelemetry import trace

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
        self.completed_posts_channels: set[str] = set()
        self.completed_posts_direct_channels: set[str] = set()
        self.last_channel_post_timestamps: dict[str, int] = {}
        self.last_channel_post_ids: dict[str, set[str]] = {}
        self.last_direct_channel_post_timestamps: dict[str, int] = {}
        self.last_direct_channel_post_ids: dict[str, set[str]] = {}
        self.last_post_timestamp: int = 0
        self.last_direct_post_timestamp: int = 0
        self.last_post_ids: set[str] = set()
        self.last_direct_post_ids: set[str] = set()
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
            checkpoint.completed_direct_channels = set(
                data.get("completed_direct_channels", [])
            )
            checkpoint.completed_posts_channels = set(
                data.get("completed_posts_channels", [])
            )
            checkpoint.completed_posts_direct_channels = set(
                data.get("completed_posts_direct_channels", [])
            )
            checkpoint.last_channel_post_timestamps = data.get("last_channel_post_timestamps", {})
            checkpoint.last_channel_post_ids = {
                k: set(v) for k, v in data.get("last_channel_post_ids", {}).items()
            }
            checkpoint.last_direct_channel_post_timestamps = data.get(
                "last_direct_channel_post_timestamps", {}
            )
            checkpoint.last_direct_channel_post_ids = {
                k: set(v) for k, v in data.get("last_direct_channel_post_ids", {}).items()
            }
            checkpoint.last_post_timestamp = data.get("last_post_timestamp", 0)
            checkpoint.last_direct_post_timestamp = data.get("last_direct_post_timestamp", 0)
            checkpoint.last_post_ids = set(data.get("last_post_ids", []))
            checkpoint.last_direct_post_ids = set(data.get("last_direct_post_ids", []))
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
                "completed_posts_channels": list(self.completed_posts_channels),
                "completed_posts_direct_channels": list(self.completed_posts_direct_channels),
                "last_channel_post_timestamps": self.last_channel_post_timestamps,
                "last_channel_post_ids": {
                    k: list(v) for k, v in self.last_channel_post_ids.items()
                },
                "last_direct_channel_post_timestamps": self.last_direct_channel_post_timestamps,
                "last_direct_channel_post_ids": {
                    k: list(v) for k, v in self.last_direct_channel_post_ids.items()
                },
                "last_post_timestamp": self.last_post_timestamp,
                "last_direct_post_timestamp": self.last_direct_post_timestamp,
                "last_post_ids": list(self.last_post_ids),
                "last_direct_post_ids": list(self.last_direct_post_ids),
                "stats": self.stats,
            }
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=self.path.parent, prefix=self.path.name + ".tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(f.fileno())
                os.replace(tmp_path, self.path)
            except Exception:
                if os.path.exists(tmp_path):
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_path)
                raise
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
        self._shutdown_requested = False

    def run(self) -> PipelineResult:
        self._shutdown_requested = False

        def handle_signal(
            signum: int, frame: types.FrameType | None
        ) -> None:
            LOGGER.warning(f"Received signal {signum}, requesting graceful shutdown...")
            self._shutdown_requested = True

        old_term: signal.Handlers = signal.SIG_DFL
        old_int: signal.Handlers = signal.SIG_DFL
        try:
            try:
                old_term = signal.signal(signal.SIGTERM, handle_signal)
                old_int = signal.signal(signal.SIGINT, handle_signal)
            except ValueError:
                pass

            tracer = trace.get_tracer("teams_mattermost_migration_parser.pipeline")
            with tracer.start_as_current_span("migration_pipeline_run") as span:
                span.set_attribute("correlation_id", self._config.correlation_id)
                span.set_attribute("input_path", str(self._config.input_path))
                span.set_attribute("output_path", str(self._config.output_path))

                start_time = time.perf_counter()
                bytes_processed = self._source.input_size_bytes()
                self._metrics.observe_input_bytes(bytes_processed)
                span.set_attribute("bytes_processed", bytes_processed)

                checkpoint = None
                resume_mode = False
                if self._config.resume and self._config.checkpoint_path:
                    loaded_checkpoint = MigrationCheckpoint.load(self._config.checkpoint_path)
                    if loaded_checkpoint is not None:
                        checkpoint = loaded_checkpoint
                        if getattr(self._writer, "has_existing_content", False):
                            resume_mode = True
                            self._metrics.observe_checkpoint_resume()
                            span.set_attribute("resumed", True)
                        else:
                            LOGGER.warning(
                                "checkpoint found but output file has no "
                                "existing content; starting fresh",
                                extra={
                                    "event": "resume_reset",
                                    "details": {
                                        "checkpoint_path": str(
                                            self._config.checkpoint_path
                                        )
                                    },
                                },
                            )
                            checkpoint = MigrationCheckpoint(self._config.checkpoint_path)
                    else:
                        checkpoint = MigrationCheckpoint(self._config.checkpoint_path)

                try:
                    # Fail-fast: reject unsupported schema versions before any work
                    if hasattr(self._source, "validate_schema_version"):
                        self._time_stage(
                            "schema_version_check",
                            self._source.validate_schema_version,
                        )
                    validation_result = self._time_stage(
                        "validation",
                        self._validator.validate,
                        self._source,
                    )
                    records_written = self._time_stage(
                        "render_and_write", self._write_records, checkpoint, resume_mode
                    )
                    if self._shutdown_requested:
                        raise ParserError("Pipeline execution interrupted by signal")
                    duration_seconds = time.perf_counter() - start_time
                    self._metrics.mark_success(
                        records_written=records_written,
                        duration_seconds=duration_seconds,
                    )
                    span.set_attribute("records_written", records_written)
                    span.set_attribute("teams", validation_result.team_count)
                    span.set_attribute("channels", validation_result.channel_count)
                    span.set_attribute("users", validation_result.user_count)
                    span.set_attribute("posts", validation_result.post_count)
                    span.set_status(trace.StatusCode.OK)
                except ParserError as exc:
                    self._metrics.mark_failure(type(exc).__name__)
                    LOGGER.exception(
                        "pipeline execution failed",
                        extra={"event": "pipeline_failed", "details": {"error": str(exc)}},
                    )
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    raise
                else:
                    if checkpoint:
                        checkpoint.delete()
                finally:
                    self._writer.close()
                    if hasattr(self._record_service, "close"):
                        self._record_service.close()
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
        finally:
            if old_term is not None:
                with contextlib.suppress(ValueError):
                    signal.signal(signal.SIGTERM, old_term)
            if old_int is not None:
                with contextlib.suppress(ValueError):
                    signal.signal(signal.SIGINT, old_int)

    def _write_records(self, checkpoint: MigrationCheckpoint | None, resume_mode: bool) -> int:
        records_written = 0
        active_channel_key = None
        active_direct_channel_key = None

        for record in self._record_service.iter_records(self._source):
            if self._shutdown_requested:
                LOGGER.warning("Graceful shutdown requested. Exiting record write loop.")
                break
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
                    if chan_key in checkpoint.completed_posts_channels:
                        continue
                    last_ts = checkpoint.last_channel_post_timestamps.get(chan_key, 0)
                    last_ids = checkpoint.last_channel_post_ids.get(chan_key, set())
                    if post["create_at"] < last_ts:
                        continue
                    if (
                        post["create_at"] == last_ts
                        and post["id"] in last_ids
                    ):
                        continue
                elif rec_type == "direct_channel":
                    members_key = ",".join(sorted(record["direct_channel"]["members"]))
                    if members_key in checkpoint.completed_direct_channels:
                        continue
                elif rec_type == "direct_post":
                    dpost = record["direct_post"]
                    members_key = ",".join(sorted(dpost["channel_members"]))
                    if members_key in checkpoint.completed_posts_direct_channels:
                        continue
                    last_ts = checkpoint.last_direct_channel_post_timestamps.get(members_key, 0)
                    last_ids = checkpoint.last_direct_channel_post_ids.get(members_key, set())
                    if dpost["create_at"] < last_ts:
                        continue
                    if (
                        dpost["create_at"] == last_ts
                        and dpost["id"] in last_ids
                    ):
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
                    post_ts = record["post"]["create_at"]
                    post_id = record["post"]["id"]
                    chan_key = f"{record['post']['team']}/{record['post']['channel']}"

                    if active_channel_key and active_channel_key != chan_key:
                        checkpoint.completed_posts_channels.add(active_channel_key)
                    active_channel_key = chan_key

                    if chan_key not in checkpoint.last_channel_post_timestamps:
                        checkpoint.last_channel_post_timestamps[chan_key] = 0
                        checkpoint.last_channel_post_ids[chan_key] = set()

                    last_ts = checkpoint.last_channel_post_timestamps[chan_key]
                    if post_ts > last_ts:
                        checkpoint.last_channel_post_timestamps[chan_key] = post_ts
                        checkpoint.last_channel_post_ids[chan_key] = {post_id}
                    elif post_ts == last_ts:
                        checkpoint.last_channel_post_ids[chan_key].add(post_id)

                    checkpoint.last_post_timestamp = post_ts
                    checkpoint.last_post_ids = checkpoint.last_channel_post_ids[chan_key]

                elif rec_type == "direct_channel":
                    members_key = ",".join(sorted(record["direct_channel"]["members"]))
                    checkpoint.completed_direct_channels.add(members_key)
                elif rec_type == "direct_post":
                    dpost_ts = record["direct_post"]["create_at"]
                    dpost_id = record["direct_post"]["id"]
                    members_key = ",".join(sorted(record["direct_post"]["channel_members"]))

                    if active_direct_channel_key and active_direct_channel_key != members_key:
                        checkpoint.completed_posts_direct_channels.add(
                            active_direct_channel_key
                        )
                    active_direct_channel_key = members_key

                    if members_key not in checkpoint.last_direct_channel_post_timestamps:
                        checkpoint.last_direct_channel_post_timestamps[members_key] = 0
                        checkpoint.last_direct_channel_post_ids[members_key] = set()

                    last_ts = checkpoint.last_direct_channel_post_timestamps[members_key]
                    if dpost_ts > last_ts:
                        checkpoint.last_direct_channel_post_timestamps[members_key] = dpost_ts
                        checkpoint.last_direct_channel_post_ids[members_key] = {dpost_id}
                    elif dpost_ts == last_ts:
                        checkpoint.last_direct_channel_post_ids[members_key].add(dpost_id)

                    checkpoint.last_direct_post_timestamp = dpost_ts
                    checkpoint.last_direct_post_ids = (
                        checkpoint.last_direct_channel_post_ids[members_key]
                    )

                checkpoint.stats[rec_type] = checkpoint.stats.get(rec_type, 0) + 1
                if records_written % self._config.batch_size == 0:
                    checkpoint.save()

        # Mark final active channels as completed
        if checkpoint:
            if active_channel_key:
                checkpoint.completed_posts_channels.add(active_channel_key)
            if active_direct_channel_key:
                checkpoint.completed_posts_direct_channels.add(active_direct_channel_key)
            checkpoint.save()

        self._writer.flush()
        return records_written

    def _time_stage(
        self,
        stage_name: str,
        func: Callable[..., ResultT],
        *args: object,
    ) -> ResultT:
        start_time = time.perf_counter()
        tracer = trace.get_tracer("teams_mattermost_migration_parser.pipeline")
        with tracer.start_as_current_span(stage_name) as span:
            span.set_attribute("stage", stage_name)
            try:
                result = func(*args)
                span.set_status(trace.StatusCode.OK)
                return result
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise
            finally:
                self._metrics.observe_stage_duration(stage_name, time.perf_counter() - start_time)
