# Performance Tuning

## Local stack

- Keep Mattermost plugins disabled for low-memory local environments unless you are actively testing them.
- Use the default Compose resource requests and limits as a baseline for an 8 GB workstation.
- Avoid committing generated JSONL payloads; large payloads should move to object storage in later environments.

## Parser

- The parser renders records deterministically and writes line-by-line JSONL output.
- For larger exports, split work by team, channel cohort, or date range and merge payloads downstream.
- If transformation time becomes dominant, containerize the parser app and run multiple queue-driven workers.

## Database and import path

- Validate payloads before every apply to catch schema issues early.
- Keep import windows controlled and observable.
- Use managed PostgreSQL, connection pooling, and object storage before scaling Mattermost horizontally.
