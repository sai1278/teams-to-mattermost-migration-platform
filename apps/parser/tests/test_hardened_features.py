from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from teams_mattermost_migration_parser.application.pipeline import (
    MigrationCheckpoint,
    TransformationPipeline,
)
from teams_mattermost_migration_parser.application.services import (
    ExportValidationService,
    MattermostRecordService,
)
from teams_mattermost_migration_parser.config import ParserConfig
from teams_mattermost_migration_parser.domain.exceptions import InputValidationError
from teams_mattermost_migration_parser.domain.models import (
    AttachmentRecord,
    ChannelRecord,
    DirectChannelRecord,
    PostRecord,
    TeamRecord,
    TeamsExport,
    UserRecord,
)
from teams_mattermost_migration_parser.domain.normalization import (
    AnonymizerPipeline,
    slugify,
    stable_alias,
)
from teams_mattermost_migration_parser.observability.metrics import ParserMetrics


def _config(tmp_path: Path, **overrides: Any) -> ParserConfig:
    return ParserConfig.from_inputs(
        input_path=tmp_path / "source" / "input.json",
        output_path=tmp_path / "output" / "import.jsonl",
        metrics_output_path=tmp_path / "metrics" / "parser.prom",
        **overrides,
    )


def _source_export() -> TeamsExport:
    return TeamsExport(
        users=(
            UserRecord(
                username="john-doe",
                email="john.doe@company.com",
                nickname="John Doe",
                teams=("it-team",),
            ),
            UserRecord(
                username="admin-user",
                email="admin@company.com",
                nickname="Admin",
                teams=("it-team",),
            ),
            UserRecord(
                username="sarah-khan",
                email="sarah@company.com",
                nickname="Sarah Khan",
                teams=(),
            ),
        ),
        teams=(
            TeamRecord(
                name="it-team",
                display_name="IT Team",
                members=("john-doe",),
                owners=("admin-user",),
                channels=(
                    ChannelRecord(
                        name="general",
                        display_name="General",
                        posts=(
                            PostRecord(
                                username="john-doe",
                                message="Root post",
                                timestamp_ms=1_000,
                                id="msg-1",
                            ),
                            PostRecord(
                                username="john-doe",
                                message="Reply one",
                                timestamp_ms=2_000,
                                id="msg-2",
                                parent_id="msg-1",
                            ),
                            PostRecord(
                                username="john-doe",
                                message="Reply two",
                                timestamp_ms=3_000,
                                id="msg-3",
                                parent_id="msg-2",
                            ),
                        ),
                    ),
                    ChannelRecord(
                        name="private-channel",
                        display_name="Private",
                        is_private=True,
                        members=("john-doe",),
                        owners=("admin-user",),
                    ),
                ),
            ),
        ),
        direct_channels=(
            DirectChannelRecord(
                members=("john-doe", "sarah-khan"),
                posts=(
                    PostRecord(
                        username="sarah-khan",
                        message="Later message",
                        timestamp_ms=2_000,
                    ),
                    PostRecord(
                        username="john-doe",
                        message="Earlier message",
                        timestamp_ms=1_000,
                    ),
                ),
            ),
        ),
    )


class _CollectingWriter:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.closed = False
        self.has_existing_content = True

    def write_record(self, record: Mapping[str, Any]) -> None:
        self.records.append(dict(record))

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _InMemorySource:
    def __init__(self, export: TeamsExport, size_bytes: int = 512) -> None:
        self._export = export
        self._size_bytes = size_bytes

    def iter_teams(self) -> Iterator[TeamRecord]:
        return iter(self._export.teams)

    def iter_users(self) -> Iterator[UserRecord]:
        return iter(self._export.users)

    def iter_direct_channels(self) -> Iterator[DirectChannelRecord]:
        return iter(self._export.direct_channels)

    def input_size_bytes(self) -> int:
        return self._size_bytes

    def materialize(self) -> TeamsExport:
        return self._export


def test_config_validation_and_secure_defaults(tmp_path: Path) -> None:
    config = _config(tmp_path, auth_data_field="USERNAME")

    assert config.auth_data_field == "username"
    assert config.default_password.get_secret_value() == ""
    assert config.checkpoint_path == tmp_path / "output" / "import.checkpoint.json"

    with pytest.raises(ValidationError):
        ParserConfig(
            input_path=tmp_path / "source" / "input.txt",
            output_path=tmp_path / "output" / "import.jsonl",
        )

    with pytest.raises(ValidationError):
        ParserConfig(
            input_path=tmp_path / "source" / "input.json",
            output_path=tmp_path / "output" / "import.txt",
        )

    with pytest.raises(ValidationError):
        _config(tmp_path, auth_data_field="phone")


def test_slugify_never_returns_empty_values() -> None:
    fallback_values = {slugify("!!!"), slugify("---"), slugify("###")}

    assert slugify("Hello World") == "hello-world"
    assert slugify("") == "default-slug"
    assert all(value.startswith("fallback-") for value in fallback_values)
    assert len(fallback_values) == 3


def test_anonymizer_pipeline_redacts_pii_and_usernames() -> None:
    pipeline = AnonymizerPipeline(usernames=["john-doe", "admin-user"])
    message = (
        "Contact john-doe at john.doe@company.com or +1 555-555-5555. "
        "Visit https://example.com, use EMP-12345, card 1234-5678-9012-3456, "
        "and check 192.168.1.10."
    )
    anonymized = pipeline.anonymize(message)

    assert stable_alias("john-doe") in anonymized
    assert "[REDACTED EMAIL]" in anonymized
    assert "[REDACTED PHONE]" in anonymized
    assert "[REDACTED EMPLOYEE ID]" in anonymized
    assert "[REDACTED URL]" in anonymized
    assert "[REDACTED CREDIT CARD]" in anonymized
    assert "[REDACTED IP]" in anonymized
    assert "john.doe@company.com" not in anonymized
    assert "555-555-5555" not in anonymized


def test_sso_auth_mode_removes_plaintext_passwords(tmp_path: Path) -> None:
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
                channels=(),
            ),
        ),
    )

    service = MattermostRecordService(
        _config(tmp_path, auth_service="saml", auth_data_field="email")
    )
    user_record = next(service.iter_user_records(export))["user"]

    assert user_record["auth_service"] == "saml"
    assert user_record["auth_data"] == "john.doe@company.com"
    assert "password" not in user_record


def test_thread_mapping_preserves_root_ids_and_reply_hierarchy(tmp_path: Path) -> None:
    service = MattermostRecordService(_config(tmp_path))
    posts = list(service.iter_post_records(_source_export()))

    assert [record["post"]["message"] for record in posts[:3]] == [
        "Root post",
        "Reply one",
        "Reply two",
    ]

    root = posts[0]["post"]
    reply_one = posts[1]["post"]
    reply_two = posts[2]["post"]

    assert "root_id" not in root
    assert reply_one["root_id"] == root["id"]
    assert reply_two["root_id"] == root["id"]
    assert reply_one["id"] != root["id"]
    assert reply_two["id"] != root["id"]


def test_membership_and_roles_resolution(tmp_path: Path) -> None:
    service = MattermostRecordService(_config(tmp_path))
    users = {
        record["user"]["username"]: record["user"]
        for record in service.iter_user_records(_source_export())
    }

    john_team = {team["name"]: team for team in users["john-doe"]["teams"]}
    admin_team = {team["name"]: team for team in users["admin-user"]["teams"]}

    assert john_team["it-team"]["roles"] == ["team_user"]
    assert admin_team["it-team"]["roles"] == ["team_admin", "team_user"]
    assert {channel["name"] for channel in john_team["it-team"]["channels"]} == {
        "general",
        "private-channel",
    }
    assert {channel["name"] for channel in admin_team["it-team"]["channels"]} == {
        "general",
        "private-channel",
    }


def test_direct_messages_migration_preserves_participants_and_order(tmp_path: Path) -> None:
    service = MattermostRecordService(_config(tmp_path))
    records = list(service.iter_records(_source_export()))

    direct_channels = [
        record["direct_channel"] for record in records if record["type"] == "direct_channel"
    ]
    direct_posts = [record["direct_post"] for record in records if record["type"] == "direct_post"]

    assert len(direct_channels) == 1
    assert direct_channels[0]["members"] == ["john-doe", "sarah-khan"]
    assert [post["message"] for post in direct_posts] == [
        "Earlier message",
        "Later message",
    ]
    assert all(post["id"].startswith("direct-post-") for post in direct_posts)


def test_group_dm_migration_preserves_all_participants(tmp_path: Path) -> None:
    export = TeamsExport(
        users=(
            UserRecord(
                username="john-doe",
                email="john.doe@company.com",
                nickname="John Doe",
                teams=(),
            ),
            UserRecord(
                username="sarah-khan",
                email="sarah@company.com",
                nickname="Sarah Khan",
                teams=(),
            ),
            UserRecord(
                username="admin-user",
                email="admin@company.com",
                nickname="Admin",
                teams=(),
            ),
        ),
        teams=(),
        direct_channels=(
            DirectChannelRecord(
                members=("john-doe", "sarah-khan", "admin-user"),
                posts=(
                    PostRecord(
                        username="admin-user",
                        message="Group DM hello",
                        timestamp_ms=1_000,
                    ),
                    PostRecord(
                        username="sarah-khan",
                        message="Group DM reply",
                        timestamp_ms=2_000,
                    ),
                ),
            ),
        ),
    )

    service = MattermostRecordService(_config(tmp_path))
    records = list(service.iter_records(export))

    direct_channel = next(
        record["direct_channel"] for record in records if record["type"] == "direct_channel"
    )
    direct_posts = [record["direct_post"] for record in records if record["type"] == "direct_post"]

    assert direct_channel["members"] == ["john-doe", "sarah-khan", "admin-user"]
    assert [post["message"] for post in direct_posts] == ["Group DM hello", "Group DM reply"]
    assert all(post["id"].startswith("direct-post-") for post in direct_posts)


def test_attachment_processing_copies_files_and_reports_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir = source_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    attachment_path = attachments_dir / "report.pdf"
    attachment_path.write_text("file bytes", encoding="utf-8")

    service = MattermostRecordService(_config(tmp_path))
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
                                message="See attachment",
                                timestamp_ms=1_000,
                                attachments=(
                                    AttachmentRecord(
                                        name="report.pdf",
                                        path="attachments/report.pdf",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    record = next(service.iter_post_records(export))["post"]
    copied_path = Path(tmp_path / "output" / "attachments" / record["attachments"][0]["file_id"])

    assert copied_path.exists()
    assert record["file_ids"] == [record["attachments"][0]["file_id"]]
    assert record["attachments"][0]["path"].startswith("attachments/")

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(
        "teams_mattermost_migration_parser.application.services.time.sleep",
        lambda *_args, **_kwargs: None,
    )
    missing_export = TeamsExport(
        users=export.users,
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
                                message="Missing attachment",
                                timestamp_ms=2_000,
                                attachments=(
                                    AttachmentRecord(
                                        name="missing.pdf",
                                        path="attachments/missing.pdf",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    missing_record = list(service.iter_post_records(missing_export))[0]["post"]

    assert "attachments" not in missing_record
    assert "file_ids" not in missing_record
    assert any("Failed to process attachment" in message for message in caplog.messages)


def test_metrics_collection_and_publish(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics" / "parser.prom"
    metrics = ParserMetrics(
        ParserConfig(
            input_path=tmp_path / "source" / "input.json",
            output_path=tmp_path / "output" / "import.jsonl",
            metrics_output_path=metrics_path,
        )
    )

    metrics.observe_input_bytes(128)
    metrics.observe_record("post")
    metrics.observe_stage_duration("validation", 0.25)
    metrics.observe_attachment("success")
    metrics.observe_checkpoint_resume()
    metrics.mark_success(records_written=4, duration_seconds=2.0)
    metrics.publish()

    rendered = metrics_path.read_text(encoding="utf-8")
    assert "tmmp_parser_runs_total" in rendered
    assert "tmmp_parser_records_emitted_total" in rendered
    assert "tmmp_parser_checkpoint_resumes_total" in rendered
    assert "tmmp_parser_last_run_records_total" in rendered


def test_checkpoint_resume_skips_completed_users_and_cleans_up_state(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    assert config.checkpoint_path is not None
    assert config.metrics_output_path is not None
    checkpoint = MigrationCheckpoint(config.checkpoint_path)
    checkpoint.completed_users.add("john-doe")
    checkpoint.save()

    export = _source_export()
    writer = _CollectingWriter()
    metrics = ParserMetrics(config)
    pipeline = TransformationPipeline(
        config=config,
        metrics=metrics,
        record_service=MattermostRecordService(config, metrics=metrics),
        source=_InMemorySource(export),
        validator=ExportValidationService(config),
        writer=writer,
    )

    result = pipeline.run()

    assert result.users == 3
    user_records = [
        record["user"]["username"] for record in writer.records if record["type"] == "user"
    ]
    assert user_records == ["admin-user", "sarah-khan"]
    assert not config.checkpoint_path.exists()
    assert writer.closed is True

    rendered_metrics = config.metrics_output_path.read_text(encoding="utf-8")
    assert "tmmp_parser_checkpoint_resumes_total 1.0" in rendered_metrics


def test_validation_rejects_missing_parent_reference(tmp_path: Path) -> None:
    validator = ExportValidationService(_config(tmp_path))
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
                                message="Reply to nowhere",
                                timestamp_ms=1_000,
                                id="msg-1",
                                parent_id="missing-parent",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(InputValidationError) as exc_info:
        validator.validate(export)

    assert "unknown parent" in str(exc_info.value)
