# Kubernetes Scaffolding

The Kubernetes manifests use Kustomize for environment overlays.

## Current intent

- `base/` defines batch-oriented parser execution resources and restrictive
  network policies.
- `overlays/local/` targets local cluster experimentation.
- `overlays/staging/` targets a shared environment with anonymized outputs and
  object-storage-style paths.

This scaffold focuses on the migration worker path. Mattermost itself should be
managed through the supported Mattermost Helm chart or operator in production.
