from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from teams_mattermost_migration_parser.application.pipeline import (
    MigrationCheckpoint,
    TransformationPipeline,
)
from teams_mattermost_migration_parser.application.services import (
    ExportValidationService,
    MattermostRecordService,
)
from teams_mattermost_migration_parser.config import ParserConfig
from teams_mattermost_migration_parser.domain.exceptions import (
    InputValidationError,
    SourceReadError,
)
from teams_mattermost_migration_parser.domain.models import (
    AttachmentRecord,
    ChannelRecord,
    DirectChannelRecord,
    PostRecord,
    TeamRecord,
    TeamsExport,
    UserRecord,
)
from teams_mattermost_migration_parser.infrastructure.readers import TeamsExportFileGateway
from teams_mattermost_migration_parser.infrastructure.writers import JsonlFileWriter
from teams_mattermost_migration_parser.observability.metrics import ParserMetrics


def _config(tmp_path: Path, **overrides: Any) -> ParserConfig:
    return ParserConfig.from_inputs(
        input_path=tmp_path / "source" / "input.json",
        output_path=tmp_path / "output" / "import.jsonl",
        metrics_output_path=tmp_path / "metrics" / "parser.prom",
        **overrides,
    )


def test_readers_missing_file_gateway(tmp_path: Path) -> None:
    gateway = TeamsExportFileGateway(tmp_path / "does_not_exist.json")
    with pytest.raises(SourceReadError, match="input file does not exist"):
        list(gateway.iter_users())

    with pytest.raises(SourceReadError, match="input file does not exist"):
        gateway.materialize()

    with pytest.raises(SourceReadError, match="input file does not exist"):
        gateway.validate_schema_version()


def test_readers_unsupported_schema_version(tmp_path: Path) -> None:
    bad_schema_file = tmp_path / "unsupported_schema.json"
    bad_schema_file.write_text(
        json.dumps({
            "schema_version": 2,
            "users": [],
            "teams": [],
            "direct_channels": [],
        }),
        encoding="utf-8"
    )
    gateway = TeamsExportFileGateway(bad_schema_file)
    with pytest.raises(InputValidationError, match="Unsupported schema version: 2"):
        gateway.validate_schema_version()


def test_readers_schema_invalid_user_item(tmp_path: Path) -> None:
    invalid_item_file = tmp_path / "invalid_item.json"
    invalid_item_file.write_text(
        json.dumps({
            "schema_version": 1,
            "users": [
                {
                    "username": "missing-email-and-teams"
                    # missing required email/teams/nickname will cause ValidationError
                }
            ],
            "teams": [],
            "direct_channels": [],
        }),
        encoding="utf-8"
    )
    gateway = TeamsExportFileGateway(invalid_item_file)
    with pytest.raises(InputValidationError, match="invalid object in 'users.item'"):
        list(gateway.iter_users())


def test_readers_invalid_json(tmp_path: Path) -> None:
    bad_json_file = tmp_path / "invalid.json"
    bad_json_file.write_text("{", encoding="utf-8")
    gateway = TeamsExportFileGateway(bad_json_file)
    with pytest.raises(SourceReadError):
        list(gateway.iter_users())


def test_jsonl_writer_part_rotation_and_resumption(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    base_output = output_dir / "import.jsonl"

    # Pre-create part 1 and part 2
    part1 = output_dir / "import.part001.jsonl"
    part2 = output_dir / "import.part002.jsonl"
    part1.write_text('{"type": "version"}\n', encoding="utf-8")
    part2.write_text('{"type": "user"}\n', encoding="utf-8")

    # Resumption logic: with append=True and max_chunk_mb=1
    writer = JsonlFileWriter(base_output, batch_size=1, append=True, max_chunk_mb=1)
    assert writer.append_mode is True
    # Should resolve to the highest existing part file on disk, which is part002
    assert writer._part_number == 2
    assert writer._current_path == part2
    writer.write_record({"type": "post", "message": "resumed"})
    writer.close()

    lines = part2.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"type": "user"}
    assert json.loads(lines[1]) == {"type": "post", "message": "resumed"}

    # Rotation logic: max_chunk_mb=1 and writing large record
    new_output = output_dir / "new_import.jsonl"
    writer2 = JsonlFileWriter(new_output, batch_size=1, max_chunk_mb=1)
    # Write a record that exceeds the threshold of 1 MB
    large_payload = "a" * (1024 * 1024 + 10)
    writer2.write_record({"type": "post", "payload": large_payload})
    # This record fits in part001 because check is done AFTER writing/during next write flush,
    # or let's see: during flush, we check if _current_file_bytes + buffer_bytes > max_bytes.
    # Write second record, which will trigger rotation
    writer2.write_record({"type": "post", "payload": "second"})
    writer2.close()

    new_part1 = output_dir / "new_import.part001.jsonl"
    new_part2 = output_dir / "new_import.part002.jsonl"
    assert new_part1.exists()
    assert new_part2.exists()

    part1_lines = new_part1.read_text(encoding="utf-8").splitlines()
    assert len(part1_lines) == 1
    assert "large_payload" not in part1_lines[0] # it has the first large record

    part2_lines = new_part2.read_text(encoding="utf-8").splitlines()
    # Part 2 should contain version record first, then the second record
    assert len(part2_lines) == 2
    assert json.loads(part2_lines[0]) == {"type": "version", "version": 1}
    assert json.loads(part2_lines[1]) == {"type": "post", "payload": "second"}


def test_pipeline_checkpoint_fine_grained_skipping(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    metrics = ParserMetrics(config)

    # 1. Prepare export data
    export = TeamsExport(
        users=(
            UserRecord(
                username="john-doe",
                email="john.doe@company.com",
                nickname="John Doe",
                teams=("it-team",),
            ),
            UserRecord(
                username="sarah-khan",
                email="sarah-khan@company.com",
                nickname="Sarah Khan",
                teams=(),
            ),
        ),
        teams=(
            TeamRecord(
                name="it-team",
                display_name="IT Team",
                channels=(
                    ChannelRecord(
                        name="general",
                        display_name="General",
                        posts=(
                            PostRecord(
                                username="john-doe",
                                message="post 1",
                                timestamp_ms=1000,
                                id="p1",
                            ),
                            PostRecord(
                                username="john-doe",
                                message="post 2",
                                timestamp_ms=2000,
                                id="p2",
                            ),
                            PostRecord(
                                username="john-doe",
                                message="post 3",
                                timestamp_ms=2000,
                                id="p3",
                            ),
                            PostRecord(
                                username="john-doe",
                                message="post 4",
                                timestamp_ms=3000,
                                id="p4",
                            ),
                        ),
                    ),
                    ChannelRecord(
                        name="random",
                        display_name="Random",
                        posts=(
                            PostRecord(
                                username="john-doe",
                                message="random post",
                                timestamp_ms=4000,
                                id="r1",
                            ),
                        ),
                    ),
                ),
            ),
        ),
        direct_channels=(
            DirectChannelRecord(
                members=("john-doe", "sarah-khan"),
                posts=(
                    PostRecord(
                        username="john-doe",
                        message="dm 1",
                        timestamp_ms=1000,
                        id="d1",
                    ),
                ),
            ),
        ),
    )

    # 2. Setup Checkpoint simulating partially completed run
    assert config.checkpoint_path is not None
    checkpoint = MigrationCheckpoint(config.checkpoint_path)
    checkpoint.completed_teams.add("it-team")
    checkpoint.completed_users.add("john-doe")

    # Compute expected hashed ID for post 2:
    # team: "it-team", channel: "general", post.id (which is source_key): "p2"
    payload = "it-team|general|p2"
    p2_digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    p2_hashed_id = f"post-{p2_digest}"

    # general channel posts partially done: last timestamp is 2000, completed IDs are p2_hashed_id.
    checkpoint.last_channel_post_timestamps["it-team/general"] = 2000
    checkpoint.last_channel_post_ids["it-team/general"] = {p2_hashed_id}
    checkpoint.save()

    # Create dummy output file so resume mode is active
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text('{"type": "version", "version": 1}\n', encoding="utf-8")

    class _InMemorySource:
        def __init__(self, e: TeamsExport) -> None:
            self._e = e
        def iter_teams(self) -> Any: return iter(self._e.teams)
        def iter_users(self) -> Any: return iter(self._e.users)
        def iter_direct_channels(self) -> Any: return iter(self._e.direct_channels)
        def input_size_bytes(self) -> int: return 123
        def materialize(self) -> TeamsExport: return self._e
        def validate_schema_version(self) -> None: pass

    class _CollectingWriter:
        def __init__(self) -> None:
            self.records: list[dict[str, Any]] = []
            self.has_existing_content = True
        def write_record(self, record: Mapping[str, Any]) -> None:
            self.records.append(dict(record))
        def flush(self) -> None: pass
        def close(self) -> None: pass

    writer = _CollectingWriter()
    pipeline = TransformationPipeline(
        config=config,
        metrics=metrics,
        record_service=MattermostRecordService(config, metrics=metrics),
        source=_InMemorySource(export),
        validator=ExportValidationService(config),
        writer=writer,
    )

    pipeline.run()

    # Verify what records were written
    # Teams, Users are marked as completed so their record types should NOT be written again.
    # General channel is NOT in completed_channels (it was just in posts).
    # But teams/users are completed.
    # General channel's posts:
    # - "p1" (ts 1000) < 2000 -> skipped
    # - "p2" (ts 2000) == 2000, ID in {"p2"} -> skipped
    # - "p3" (ts 2000) == 2000, ID NOT in {"p2"} -> WRITTEN
    # - "p4" (ts 3000) > 2000 -> WRITTEN
    # - "r1" (ts 4000) on "random" channel -> WRITTEN
    # - "d1" (ts 1000) on direct channel -> WRITTEN

    post_messages = [
        rec["post"]["message"] for rec in writer.records if rec.get("type") == "post"
    ]
    assert "post 1" not in post_messages
    assert "post 2" not in post_messages
    assert "post 3" in post_messages
    assert "post 4" in post_messages
    assert "random post" in post_messages

    dm_messages = [
        rec["direct_post"]["message"] for rec in writer.records if rec.get("type") == "direct_post"
    ]
    assert "dm 1" in dm_messages


def test_services_concurrent_attachment_download_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config = _config(tmp_path, attachment_workers=2)
    metrics = ParserMetrics(config)
    service = MattermostRecordService(config, metrics=metrics)

    # Prepare export with attachment
    export = TeamsExport(
        users=(
            UserRecord(
                username="john-doe",
                email="john.doe@company.com",
                nickname="John Doe",
                teams=("it-team",),
            ),
        ),
        teams=(
            TeamRecord(
                name="it-team",
                display_name="IT Team",
                channels=(
                    ChannelRecord(
                        name="general",
                        display_name="General",
                        posts=(
                            PostRecord(
                                username="john-doe",
                                message="post 1",
                                timestamp_ms=1000,
                                attachments=(
                                    AttachmentRecord(
                                        name="failing.pdf",
                                        path="attachments/failing.pdf",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    # We want it to raise ValueError inside the thread pool executor (first call),
    # but NOT during the rendering phase (second call) so that it doesn't crash the generator.
    call_count = 0
    original_process = service._process_attachment

    def mock_process(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("Simulated concurrent failure")
        return original_process(*args, **kwargs)

    service._process_attachment = mock_process  # type: ignore[assignment]

    monkeypatch.setattr(
        "teams_mattermost_migration_parser.application.services.time.sleep",
        lambda *_args, **_kwargs: None,
    )

    with caplog.at_level(logging.WARNING):
        records = list(service.iter_records(export))

    # Verify warning logged and it completed without crashing
    expected_msg = "Concurrent attachment download failed: Simulated concurrent failure"
    assert any(expected_msg in msg for msg in caplog.messages)
    assert len(records) > 0
