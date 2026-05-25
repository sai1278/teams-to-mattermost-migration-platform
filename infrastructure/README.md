# Infrastructure Layout

The infrastructure directory is split by deployment surface:

- `docker/` contains the local developer control plane and observability stack.
- `monitoring/` contains Prometheus, Grafana, Loki, and Promtail configuration.
- `kubernetes/` contains future-ready Kustomize overlays for batch execution in
  a cluster.

This layout keeps local development simple while making the migration path to
managed databases, Redis, object storage, and queue-backed workers explicit.
