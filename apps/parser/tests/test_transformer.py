from __future__ import annotations

import json
from pathlib import Path

from teams_mattermost_migration_parser.config import ParserConfig
from teams_mattermost_migration_parser.domain import InputValidationError
from teams_mattermost_migration_parser.transformer import TeamsExportTransformer, load_export

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample-teams-export.json"
INVALID_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "invalid-teams-export.json"


def test_transformer_emits_expected_record_count(tmp_path: Path) -> None:
    export = load_export(FIXTURE_PATH)
    config = ParserConfig(
        input_path=FIXTURE_PATH,
        output_path=tmp_path / "import.jsonl",
    )

    record_count = TeamsExportTransformer(config).write_records(export)

    lines = config.output_path.read_text(encoding="utf-8").strip().splitlines()
    assert record_count == 13
    assert len(lines) == 13
    assert json.loads(lines[0]) == {"type": "version", "version": 1}


def test_transformer_scrubs_pii_when_anonymize_is_enabled(tmp_path: Path) -> None:
    export = load_export(FIXTURE_PATH)
    config = ParserConfig(
        input_path=FIXTURE_PATH,
        output_path=tmp_path / "import.jsonl",
        anonymize=True,
    )

    TeamsExportTransformer(config).write_records(export)
    lines = [
        json.loads(line) for line in config.output_path.read_text(encoding="utf-8").splitlines()
    ]

    user_records = [line["user"] for line in lines if line.get("type") == "user"]
    post_records = [line["post"] for line in lines if line.get("type") == "post"]

    assert all(record["email"].endswith("@example.invalid") for record in user_records)
    assert any(record["message"] == "[PII SCRUBBED]" for record in post_records)


def test_transformer_preserves_private_channel_type(tmp_path: Path) -> None:
    export = load_export(FIXTURE_PATH)
    config = ParserConfig(
        input_path=FIXTURE_PATH,
        output_path=tmp_path / "import.jsonl",
    )

    TeamsExportTransformer(config).write_records(export)
    lines = [
        json.loads(line) for line in config.output_path.read_text(encoding="utf-8").splitlines()
    ]

    channel_records = [line["channel"] for line in lines if line.get("type") == "channel"]
    assert any(channel["type"] == "P" for channel in channel_records)


def test_streaming_pipeline_rejects_invalid_cross_references(tmp_path: Path) -> None:
    config = ParserConfig(
        input_path=INVALID_FIXTURE_PATH,
        output_path=tmp_path / "import.jsonl",
    )

    transformer = TeamsExportTransformer(config)

    try:
        transformer.run()
    except InputValidationError as exc:
        assert "missing from users" in str(exc)
        assert "unknown teams" in str(exc)
    else:
        raise AssertionError("expected the invalid fixture to fail validation")
