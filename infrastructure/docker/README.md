# Docker Runtime

This directory contains the local control plane for platform development.

## Files

- `docker-compose.yml` starts PostgreSQL, Mattermost, and an optional parser
  tooling container.
- `docker-compose.monitoring.yml` starts Prometheus, Grafana, Loki, Promtail,
  Pushgateway, cAdvisor, and postgres-exporter.
- `.env.example` defines local runtime defaults and documents future cloud-ready
  settings such as object storage and Redis endpoints.

## Design notes

- The parser image is built from `apps/parser/Dockerfile`.
- The parser service runs behind the `tooling` profile to avoid unnecessary
  container startup during normal application development.
- Monitoring is intentionally split into a second Compose file to keep the core
  platform loop lightweight.
