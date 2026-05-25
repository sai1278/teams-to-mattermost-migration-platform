# Local Development Runbook

## Standard loop

```bash
make bootstrap
make install-dev
make up
make transform
make validate
make apply
make verify
```

## Cleanup

```bash
make down
make monitoring-down
make reset
```

Use `make reset` when you need to remove containers, networks, volumes, and generated artifacts for a clean rerun.
