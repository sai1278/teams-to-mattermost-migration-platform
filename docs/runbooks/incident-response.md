# Incident Response Runbook

## Incident classes

- import validation failures
- partial or failed apply operations
- Mattermost startup regressions
- observability pipeline failures

## First response checklist

1. Run `make health`.
2. Gather logs from `docker compose logs`.
3. Confirm the last transformed payload and input source.
4. Verify PostgreSQL counts with `make verify`.
5. Decide whether the failure is recoverable or if a local reset is faster.

## Recovery patterns

- Validation failures: fix the export contract and regenerate the payload.
- Mattermost readiness failures: inspect container logs, database health, and `.env` drift.
- Local data corruption: snapshot evidence, then run `make reset` and replay the workflow.
