# Observability Stack

The local observability stack includes:

- Prometheus for metrics
- Grafana for dashboards
- Loki for logs
- Promtail for Docker log collection
- Pushgateway for short-lived parser job metrics
- cAdvisor for container metrics
- postgres-exporter for database metrics

## Start and stop

```bash
make monitoring-up
make monitoring-down
```

## Signals

- Mattermost metrics are exposed on port `8067` inside the Compose network.
- PostgreSQL metrics come from `postgres-exporter`.
- Container CPU and memory usage come from cAdvisor.
- Docker logs are scraped by Promtail and shipped to Loki.
- Parser throughput, last-run volume, and failures are published through
  Pushgateway and scraped by Prometheus.

## Dashboard

Grafana provisions the `Migration Platform Control Plane` dashboard
automatically at startup. It focuses on availability, container resource usage,
and platform log streams.
