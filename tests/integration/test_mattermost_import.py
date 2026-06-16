from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "infrastructure" / "docker"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample-teams-export.json"


def has_docker() -> bool:
    try:
        # Check if docker daemon is reachable
        res = subprocess.run(["docker", "info"], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not has_docker(), reason="Docker daemon not available")
def test_mattermost_import_end_to_end(tmp_path: Path) -> None:
    # 1. Generate JSONL file
    output_path = tmp_path / "import.jsonl"
    metrics_path = tmp_path / "parser.prom"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "apps" / "parser" / "src")

    # Run CLI
    subprocess.run(
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
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    # Load .env.example values for docker-compose environment defaults
    env_example_path = COMPOSE_DIR / ".env.example"
    docker_env = os.environ.copy()
    if env_example_path.exists():
        for line in env_example_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                docker_env[k.strip()] = v.strip()

    # Overwrite postgres password for safety in test
    docker_env["POSTGRES_PASSWORD"] = "test-password-123"

    # Start container stack
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_DIR / "docker-compose.yml"),
            "up",
            "-d",
            "postgres",
            "mattermost",
        ],
        check=True,
        cwd=str(COMPOSE_DIR),
        env=docker_env,
    )

    try:
        # Wait for Mattermost to be healthy
        healthy = False
        for _ in range(30):
            res = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(COMPOSE_DIR / "docker-compose.yml"),
                    "ps",
                    "mattermost",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                cwd=str(COMPOSE_DIR),
                env=docker_env,
            )
            if "healthy" in res.stdout:
                healthy = True
                break
            time.sleep(2)

        assert healthy, "Mattermost container did not become healthy in time"

        # Copy output_path to Mattermost container and run import
        subprocess.run(
            [
                "docker",
                "cp",
                str(output_path),
                "teams-mattermost-migration-mattermost-1:/tmp/import.jsonl",
            ],
            check=True,
        )

        # Run bulk import command
        import_res = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "teams-mattermost-migration-mattermost-1",
                "mattermost",
                "import",
                "bulk",
                "/tmp/import.jsonl",
                "--apply",
            ],
            capture_output=True,
            text=True,
        )
        error_msg = f"Import failed: {import_res.stderr}\nStdout: {import_res.stdout}"
        assert import_res.returncode == 0, error_msg

    finally:
        # Tear down container stack
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_DIR / "docker-compose.yml"),
                "down",
                "-v",
            ],
            cwd=str(COMPOSE_DIR),
            env=docker_env,
        )


@pytest.mark.skipif(not has_docker(), reason="Docker daemon not available")
def test_mattermost_import_idempotency(tmp_path: Path) -> None:
    # 1. Generate JSONL file
    output_path = tmp_path / "import.jsonl"
    metrics_path = tmp_path / "parser.prom"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "apps" / "parser" / "src")

    # Run CLI
    subprocess.run(
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
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    # Load .env.example values for docker-compose environment defaults
    env_example_path = COMPOSE_DIR / ".env.example"
    docker_env = os.environ.copy()
    if env_example_path.exists():
        for line in env_example_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                docker_env[k.strip()] = v.strip()

    # Overwrite postgres password for safety in test
    docker_env["POSTGRES_PASSWORD"] = "test-password-123"

    # Start container stack
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_DIR / "docker-compose.yml"),
            "up",
            "-d",
            "postgres",
            "mattermost",
        ],
        check=True,
        cwd=str(COMPOSE_DIR),
        env=docker_env,
    )

    try:
        # Wait for Mattermost to be healthy
        healthy = False
        for _ in range(30):
            res = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(COMPOSE_DIR / "docker-compose.yml"),
                    "ps",
                    "mattermost",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                cwd=str(COMPOSE_DIR),
                env=docker_env,
            )
            if "healthy" in res.stdout:
                healthy = True
                break
            time.sleep(2)

        assert healthy, "Mattermost container did not become healthy in time"

        # Copy output_path to Mattermost container and run import
        subprocess.run(
            [
                "docker",
                "cp",
                str(output_path),
                "teams-mattermost-migration-mattermost-1:/tmp/import.jsonl",
            ],
            check=True,
        )

        # Run bulk import command first time
        import_res = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "teams-mattermost-migration-mattermost-1",
                "mattermost",
                "import",
                "bulk",
                "/tmp/import.jsonl",
                "--apply",
            ],
            capture_output=True,
            text=True,
        )
        error_msg_1 = f"Import 1 failed: {import_res.stderr}\nStdout: {import_res.stdout}"
        assert import_res.returncode == 0, error_msg_1

        # Count posts in database after first import
        res = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_DIR / "docker-compose.yml"),
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                docker_env.get("POSTGRES_USER", "mmuser"),
                "-d",
                docker_env.get("POSTGRES_DB", "mattermost"),
                "-tAc",
                "SELECT COUNT(*) FROM posts;",
            ],
            capture_output=True,
            text=True,
            cwd=str(COMPOSE_DIR),
            env=docker_env,
        )
        post_count_first = int(res.stdout.strip())

        # Run bulk import command second time
        import_res2 = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "teams-mattermost-migration-mattermost-1",
                "mattermost",
                "import",
                "bulk",
                "/tmp/import.jsonl",
                "--apply",
            ],
            capture_output=True,
            text=True,
        )
        error_msg_2 = f"Import 2 failed: {import_res2.stderr}\nStdout: {import_res2.stdout}"
        assert import_res2.returncode == 0, error_msg_2

        # Run SQL cleanup to enforce idempotency
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_DIR / "docker-compose.yml"),
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                docker_env.get("POSTGRES_USER", "mmuser"),
                "-d",
                docker_env.get("POSTGRES_DB", "mattermost"),
                "-c",
                "DELETE FROM posts WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY substring(props from '\"import_id\"\\s*:\\s*\"([^\"]+)\"') ORDER BY createat ASC, id ASC) as rn FROM posts) t WHERE rn > 1);",
            ],
            check=True,
            cwd=str(COMPOSE_DIR),
            env=docker_env,
        )

        # Count posts in database after second import + cleanup
        res2 = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_DIR / "docker-compose.yml"),
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                docker_env.get("POSTGRES_USER", "mmuser"),
                "-d",
                docker_env.get("POSTGRES_DB", "mattermost"),
                "-tAc",
                "SELECT COUNT(*) FROM posts;",
            ],
            capture_output=True,
            text=True,
            cwd=str(COMPOSE_DIR),
            env=docker_env,
        )
        post_count_second = int(res2.stdout.strip())

        # Assert post counts are identical, demonstrating idempotency
        assert post_count_first > 0
        assert post_count_second == post_count_first

    finally:
        # Tear down container stack
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_DIR / "docker-compose.yml"),
                "down",
                "-v",
            ],
            cwd=str(COMPOSE_DIR),
            env=docker_env,
        )
