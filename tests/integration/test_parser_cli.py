from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample-teams-export.json"


def test_cli_generates_jsonl_payload(tmp_path: Path) -> None:
    output_path = tmp_path / "generated-import.jsonl"
    metrics_path = tmp_path / "parser.prom"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "apps" / "parser" / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "teams_mattermost_migration_parser.cli",
            "--input",
            str(FIXTURE_PATH),
            "--output",
            str(output_path),
            "--metrics-output",
            str(metrics_path),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert metrics_path.exists()

    rendered = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rendered[0]["type"] == "version"
    assert any(item.get("type") == "post" for item in rendered)
