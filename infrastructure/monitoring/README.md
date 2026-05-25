# Monitoring Stack

The monitoring stack is built around Prometheus, Grafana, Loki, Promtail, and
Pushgateway.

## Signals

- Mattermost service metrics
- PostgreSQL exporter metrics
- Container CPU and memory metrics
- Parser throughput and failure metrics pushed from the CLI
- Docker log streams collected by Promtail and stored in Loki

## Alerting

Prometheus alert rules live under `prometheus/rules/` and currently cover:

- Mattermost availability
- parser failures
- degraded parser throughput
