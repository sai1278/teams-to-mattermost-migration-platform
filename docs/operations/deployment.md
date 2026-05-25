# Deployment Procedures

## Local Docker deployment

Use the Makefile targets for normal lifecycle management:

```bash
make up
make monitoring-up
```

The bootstrap and lifecycle scripts enforce:

- explicit `.env` handling
- health-based startup ordering
- idempotent Compose entrypoints
- a clean separation between core services and monitoring services

## Kubernetes preparation

The repository includes a Kustomize base and overlay structure for parser job execution:

- `infrastructure/kubernetes/base/`
- `infrastructure/kubernetes/overlays/local/`
- `infrastructure/kubernetes/overlays/staging/`

This does not replace the official Mattermost Helm chart or operator. Instead,
it shows how the migration worker can be promoted into cluster-native batch
execution while Mattermost itself is managed on a supported platform surface.
