# Migration Execution Runbook

## Safe import sequence

1. Start the platform with `make up`.
2. Generate a payload with `make transform`.
3. Validate the payload with `make validate`.
4. Apply the payload with `make apply`.
5. Verify database state with `make verify`.

## Rollback guidance

- For local development, use `make reset` to destroy the test environment and rerun the flow.
- For shared environments, snapshot PostgreSQL before apply operations.
- Keep payloads versioned and immutable so imports can be replayed or audited.

## Operator checkpoints

- The input export path is correct.
- Mattermost is healthy before validation begins.
- Validation passes before any apply step.
- Verification counts are non-zero after apply.
