# Test Report

## Results

- `pytest`: pass, 26 tests.
- Coverage: pass, 90.03 percent line coverage.
- `ruff check`: pass.
- `ruff format --check`: pass.
- `mypy`: pass.

## Additional Validation

- `yamllint`: pass after doc cleanup.
- `markdownlint-cli`: pass after doc cleanup.
- `pip-audit`: pass for runtime and dev dependencies.

## Coverage Focus

- CLI execution path.
- Streaming export reader success and error paths.
- JSONL writer batching and append mode.
- Logging, metrics, and checkpoint recovery.
- Thread mapping, memberships, attachments, and direct messages.
