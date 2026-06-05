# Security Review

## Positive Findings

- Password export is disabled by default.
- SSO modes use `auth_service` and `auth_data` without plaintext passwords.
- Attachment handling copies files locally and logs failures safely.
- Dependency scanning is present through `pip-audit` and CI workflows.
- Secret scanning and SBOM generation are part of the security workflow.

## Residual Risk

- Temporary password mode is still opt-in and should be used sparingly.
- Local Docker and Kubernetes resources inherit the host environment trust.
- Large migrations should still be run with least-privilege credentials.

## Recommendation

- Prefer SSO for production imports.
- Use temporary passwords only when the target workspace requires them.
- Keep dependency and secret scanning enabled in CI.
