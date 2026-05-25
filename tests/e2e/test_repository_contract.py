from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_expected_enterprise_directories_exist() -> None:
    expected = [
        "apps/parser/src",
        "apps/parser/tests",
        "infrastructure/docker",
        "infrastructure/monitoring",
        "infrastructure/kubernetes/base",
        "docs/architecture",
        "docs/operations",
        "docs/observability",
        "docs/security",
        "docs/troubleshooting",
        "docs/runbooks",
        "tests/integration",
        "tests/e2e",
        "tests/fixtures",
    ]
    for path in expected:
        assert (REPO_ROOT / path).exists(), path
