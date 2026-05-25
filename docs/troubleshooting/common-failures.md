# Common Failures

## Docker is not reachable

Symptoms:

- `make up` fails immediately
- health checks report that the daemon is unavailable

Actions:

- start Docker Desktop or Docker Engine
- confirm WSL2 integration is enabled
- rerun `make health`

## Mattermost never becomes healthy

Symptoms:

- `make up` waits until timeout
- the `/api/v4/system/ping` endpoint never returns `200`

Actions:

- inspect `docker compose -f infrastructure/docker/docker-compose.yml logs mattermost`
- verify PostgreSQL is healthy first
- confirm the `.env` credentials match the Compose settings

## Validation fails

Symptoms:

- `make validate` exits non-zero

Actions:

- rerun `make transform` to regenerate the JSONL payload
- inspect the parser logs in the terminal output
- verify the input contract in `tests/fixtures/` or your upstream export adapter

## Grafana has no logs

Symptoms:

- dashboards load but the log panel is empty

Actions:

- confirm `promtail` is running
- confirm Docker log access mounts are available in your WSL2 environment
- query Loki directly from Grafana Explore to validate label discovery
