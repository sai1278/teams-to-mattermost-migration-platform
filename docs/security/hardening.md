# Security Hardening

## Local defaults

- `.env` is generated from a tracked example and ignored by Git.
- Containers use `no-new-privileges` where supported.
- The data network is internal to reduce accidental exposure of PostgreSQL.
- The parser can anonymize user data and scrub sensitive text for demos and lower environments.

## Production guidance

- Move credentials into a secret manager or Kubernetes Secrets backed by an external KMS.
- Use managed PostgreSQL with TLS and least-privilege database users.
- Store payloads in encrypted object storage rather than local disk.
- Run queue workers and parser jobs with dedicated service accounts and restrictive network policies.
- Keep dependency and filesystem scanning enabled in CI through `pip-audit`,
  `gitleaks`, `trivy`, and SBOM generation.
