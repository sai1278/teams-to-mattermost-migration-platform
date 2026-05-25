# Parser Application

The parser application converts a normalized Microsoft Teams export contract into
a Mattermost bulk import payload.

## Architecture

- `domain/` contains immutable business models, normalization helpers, and
  exception types.
- `application/` owns validation, record rendering, and pipeline orchestration.
- `infrastructure/` owns streaming file readers and batched JSONL writers.
- `observability/` owns structured logging, correlation IDs, and Prometheus
  metrics publication.

## Operational behavior

- Input parsing is pass-based and streaming to reduce memory pressure on large
  exports.
- Validation runs before records are emitted so imports fail fast on bad data.
- JSONL output is flushed in batches to reduce syscall overhead.
- Metrics can be written to a Prometheus textfile and optionally pushed to a
  Pushgateway.

## Local usage

```bash
python -m teams_mattermost_migration_parser.cli \
  --input tests/fixtures/sample-teams-export.json \
  --output artifacts/imports/sample-import.jsonl \
  --metrics-output artifacts/metrics/parser.prom
```

Install the package in editable mode when you want direct module execution:

```bash
python -m pip install -e apps/parser
```
