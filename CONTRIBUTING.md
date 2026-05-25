# Contributing

## Development model

Treat this repository like a platform engineering codebase:

- prefer small, reviewable changes
- keep infrastructure, docs, and automation in sync
- preserve deterministic local workflows
- bias toward operational clarity over cleverness

## Local setup

```bash
make bootstrap
make install-dev
```

The bootstrap step copies `infrastructure/docker/.env.example` to `.env` when
needed. Review the generated file before starting services.

## Standards

- Python code lives under `apps/parser/src/`.
- Shell entrypoints live under `scripts/` and should source `scripts/lib/common.sh`.
- Generated payloads belong in `artifacts/` and should not be committed.
- Documentation changes should be updated with the code or operational change they describe.

## Validation before opening a PR

```bash
make lint
make test
make security
```

For infrastructure changes, also run:

```bash
make docker-validate
```

## Commit guidance

- Use commit messages that describe the operator or platform impact.
- Call out rollback considerations when changing shell automation or Compose manifests.
- Include screenshots only for user-facing dashboard changes.
