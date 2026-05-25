# Onboarding

## Workstation requirements

- Windows 11 with WSL2 Ubuntu or a native Linux workstation
- Docker Desktop or Docker Engine with Compose v2
- Python 3.11+
- GNU Make

## First-day setup

```bash
make bootstrap
make install-dev
make pre-commit-install
make up
make health
```

## Mental model

- `apps/parser/` is the application layer.
- `scripts/` is the operator interface.
- `infrastructure/docker/` is the local control plane.
- `infrastructure/kubernetes/` is the future cluster path.
- `docs/` contains the operational context you would hand to an SRE or new platform engineer.
