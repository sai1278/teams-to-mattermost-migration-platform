# SECURITY REVIEW
## Teams → Mattermost Migration Platform
**Audit Date:** 2026-06-08  
**Reviewer Role:** Staff Software Engineer / Principal SRE  
**Security Posture:** Defense-in-depth with multiple layers

---

## 1. Credential & Secret Management

### 1.1 Default Password Policy

**Finding:** SECURE ✅  
**Evidence:** `constants.py:8` — `DEFAULT_DEFAULT_PASSWORD: Final[str] = ""`

The default password is an empty string. No password key is emitted in JSONL unless explicitly configured. This is the correct antipattern reversal — previous tools often shipped with hardcoded defaults.

```python
# config.py:51
default_password: SecretStr = SecretStr(DEFAULT_DEFAULT_PASSWORD)
```

`SecretStr` from Pydantic prevents accidental inclusion in `str(config)`, `repr(config)`, or JSON serialization outputs. The value is only accessible via `.get_secret_value()`.

**Test Evidence:**
```
PASSED test_hardened_features.py::test_config_validation_and_secure_defaults
# Asserts: config.default_password.get_secret_value() == ""
```

**Residual Risk:** CLI `--default-password` flag passes the value as a command-line argument, visible in `ps aux`. **Remediation:** Document that `TMMP_DEFAULT_PASSWORD` env var is the preferred method. Add warning log when password is set via CLI.

### 1.2 SSO / SAML Auth Mode

**Finding:** SECURE ✅  
When `auth_service` is configured, `password` is explicitly absent from user records.

```python
# services.py:481-491
if self._config.auth_service:
    user_data["auth_service"] = self._config.auth_service
    user_data["auth_data"] = user.email  # no "password" key
```

**Test Evidence:**
```
PASSED test_hardened_features.py::test_sso_auth_mode_removes_plaintext_passwords
# Asserts: "password" not in user_record
```

### 1.3 Secrets in JSONL Output

**Finding:** RISK ⚠️  
When a non-empty default password is configured, it appears in plaintext in the JSONL output file. The JSONL file must be treated as a sensitive artifact.

**Remediation:**
1. Apply `chmod 600` to the output JSONL file in the migration scripts
2. Do not store JSONL files in version control
3. Delete JSONL files after successful Mattermost import (`make apply` should include cleanup)

---

## 2. Container Security

### 2.1 Non-Root Container Execution

**Finding:** SECURE ✅  
**Evidence:** `apps/parser/Dockerfile:22-23`

```dockerfile
RUN groupadd --gid 65532 parser && \
    useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin parser
USER 65532:65532
```

Docker Compose enforces non-root: `user: "65532:65532"` (compose.yml:134)  
Mattermost enforces non-root: `user: "2000:2000"` (compose.yml:69)

### 2.2 Read-Only Filesystem

**Finding:** SECURE ✅  
**Evidence:** `docker-compose.yml:135`

```yaml
read_only: true
tmpfs:
  - /tmp
```

Parser container has a read-only root filesystem with only `/tmp` as a writable tmpfs mount. Artifact directories are volume-mounted.

### 2.3 No New Privileges

**Finding:** SECURE ✅  
**Evidence:** Both `docker-compose.yml` and Kubernetes manifests

```yaml
# compose.yml
security_opt:
  - no-new-privileges:true

# kubernetes/base/parser-job.yaml
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
```

### 2.4 Privileged Container

**Finding:** RISK ⚠️  
**Evidence:** `docker-compose.monitoring.yml:70`

```yaml
cadvisor:
  privileged: true
  devices:
    - /dev/kmsg:/dev/kmsg
```

cAdvisor requires privileged mode for container metrics collection. This is a known requirement, not a defect. **Mitigation:** cAdvisor is on the internal `data` network, not exposed publicly. Consider using OpenTelemetry Collector with a host-mounted socket as an alternative.

### 2.5 Base Image Currency

**Finding:** RISK ⚠️  
Dockerfile uses `python:3.12-slim` without a digest pin:

```dockerfile
FROM python:3.12-slim AS builder
```

Unpinned tags can pull different images on each build, potentially introducing vulnerabilities silently.

**Remediation:**
```dockerfile
FROM python:3.12-slim@sha256:<digest> AS builder
```

Or pin via Dependabot Docker ecosystem configuration.

---

## 3. Network Security

### 3.1 Docker Network Isolation

**Finding:** SECURE ✅

```yaml
networks:
  platform:
    driver: bridge      # External-facing services
  data:
    driver: bridge
    internal: true       # Database-only, no external connectivity
```

PostgreSQL is on the `data` network only (no internet access). Mattermost is on both networks to reach postgres. Parser is on `platform` only.

### 3.2 Kubernetes Network Policy

**Finding:** SECURE ✅  
**Evidence:** `infrastructure/kubernetes/base/networkpolicy.yaml`

```yaml
policyTypes:
  - Egress
egress:
  - to:
      - namespaceSelector: {}  # Any namespace
    ports:
      - TCP: 5432  # PostgreSQL
      - TCP: 6379  # Redis (future)
      - TCP: 443   # HTTPS (attachment downloads)
```

Ingress is implicitly denied (no Ingress rule). Egress is restricted to only needed ports. Note: Ingress NetworkPolicy should be added explicitly for defense-in-depth.

**Gap:** No `Ingress` PolicyType defined — while `policyTypes: [Egress]` applies only to egress, adding `Ingress: []` would explicitly deny all inbound traffic as well.

### 3.3 Port Binding

**Finding:** SECURE ✅  
PostgreSQL only binds to loopback: `127.0.0.1:${POSTGRES_PORT}:5432` (compose.yml:41). Not exposed on `0.0.0.0`.

---

## 4. Dependency Security

### 4.1 pip-audit Results

**Finding:** SECURE ✅  
**Execution Evidence:**
```
$ python -m pip_audit -r apps/parser/requirements.txt
No known vulnerabilities found
```

Runtime dependencies (5 packages): `email-validator`, `ijson`, `prometheus-client`, `pydantic-settings`, `pydantic` — all clean.

### 4.2 Dependabot Configuration

**Finding:** SECURE ✅  
**Evidence:** `.github/dependabot.yml`

Weekly automated PRs for:
- GitHub Actions dependencies (`/`)
- Root pip dependencies (`/`)
- Parser pip dependencies (`/apps/parser`)

Major version updates are ignored (conservative policy preventing breaking changes from automated PRs).

### 4.3 Trivy + SBOM

**Finding:** SECURE ✅  
**Evidence:** `.github/workflows/security.yml:47-70`

- Trivy filesystem scan on every push/PR → SARIF uploaded to GitHub Code Scanning
- Anchore Syft SBOM generation in SPDX-JSON format
- Results visible in GitHub Security tab

### 4.4 Gitleaks Secret Scanning

**Finding:** SECURE ✅  
**Evidence:** `.github/workflows/security.yml:35-45`

Full git history scanned with `fetch-depth: 0`. Runs on push, PR, and weekly schedule.

---

## 5. Data Protection & PII

### 5.1 Anonymization Pipeline

**Finding:** CONDITIONALLY SECURE ⚠️  
**Evidence:** `domain/normalization.py:30-82`

Multi-layer PII redaction:
- Keyword scrub (confidential/secret/restricted) → `[PII SCRUBBED]`
- Credit card (13-19 digit patterns) → `[REDACTED CREDIT CARD]`
- Email (standard RFC-ish regex) → `[REDACTED EMAIL]`
- Phone (N. American + international) → `[REDACTED PHONE]`
- Employee ID (EMP-NNNN, ENNNNN) → `[REDACTED EMPLOYEE ID]`
- URL (http/https) → `[REDACTED URL]`
- IP address (IPv4 only) → `[REDACTED IP]`
- Usernames (word-boundary replacement) → deterministic `user-{sha1}`

**Test Evidence:**
```
PASSED test_hardened_features.py::test_anonymizer_pipeline_redacts_pii_and_usernames
```

**Gaps:**
1. IPv6 addresses not redacted
2. Phone regex may over-match dates (`2023-12-31`, `1716-537-600`)
3. URL regex does not catch bare IP:port (`192.168.1.1:8080`)
4. `SCRUB_KEYWORDS` is hardcoded — not configurable without code change
5. Credit card regex `\b(?:\d[ -]*?){13,19}\b` could match long numeric sequences (timestamps, tracking IDs)

### 5.2 `stable_alias` Identifiability

**Finding:** ACCEPTABLE ⚠️  
`stable_alias` uses `sha1(username)[:10]` (40-bit prefix). This is deterministic — the same username always maps to the same alias — but is reversible via rainbow table for known username formats.

For organizations where usernames follow predictable patterns (firstname.lastname), pre-image attack is feasible. Consider using HMAC with a per-migration secret key for stronger anonymization.

### 5.3 Attachment File Security

**Finding:** RISK ⚠️  
Attachment filename sanitization: `re.sub(r"[^a-zA-Z0-9.-]+", "_", orig_name)` (services.py:316)

This **allows dots** in the whitelist, which could permit:
- `../../etc/passwd` → `.._.._etc_passwd` (sanitized, safe)  
- `file.php` → `file.php` (kept as-is)

The hash prefix (`{sha256[:8]}_filename`) prevents collisions and limits the impact. However, if the attachment directory is served via a web server, `.php` files could be executed. **Remediation:** Strip file extensions or map to safe extensions only in web-serving contexts.

---

## 6. Security Scanning Summary

| Control | Status | Evidence |
|---------|--------|----------|
| Non-root containers | ✅ | Dockerfile:22-23, compose.yml:69,134 |
| Read-only filesystem | ✅ | compose.yml:135 |
| No new privileges | ✅ | compose.yml:53-54, parser-job.yaml:16 |
| Seccomp RuntimeDefault | ✅ | parser-job.yaml:17-18 |
| Default empty password | ✅ | constants.py:8, test evidence |
| SSO removes password key | ✅ | services.py:481-491, test evidence |
| SecretStr for password | ✅ | config.py:51 |
| pip-audit clean | ✅ | Execution: No vulnerabilities |
| Gitleaks secret scan | ✅ | security.yml:35-45 |
| Trivy filesystem scan | ✅ | security.yml:47-70 |
| SBOM generation | ✅ | security.yml:65-70 |
| Dependabot weekly | ✅ | dependabot.yml |
| DB network isolated | ✅ | compose.yml network:data:internal |
| K8s NetworkPolicy | ✅ | networkpolicy.yaml |
| PII anonymization | ⚠️ | IPv6 gap, keyword hardcoded |
| SSL attachment downloads | ⚠️ | urllib default behavior |
| Base image digest pin | ❌ | Dockerfile uses `python:3.12-slim` |
| cAdvisor privileged | ⚠️ | Required; mitigated by network isolation |

---

## 7. Security Recommendations (Priority Order)

### Critical
1. **Pin Docker base image to digest** — prevents supply-chain image substitution

### High
2. **Add SSL context to `urllib.request.urlopen`** — enforce certificate validation for attachment downloads
3. **Protect JSONL output file permissions** — `chmod 600` in migration scripts
4. **Add attachment file size limit** — prevent disk exhaustion from malicious URLs

### Medium
5. **HMAC-based `stable_alias`** — prevent rainbow-table de-anonymization
6. **Configurable SCRUB_KEYWORDS** — support `TMMP_SCRUB_KEYWORDS` env var
7. **Explicit K8s Ingress NetworkPolicy** — deny all inbound traffic
8. **Explicit file extension allowlist** for attachments

### Low
9. **Warn when password is set via CLI arg** (visible in ps aux)
10. **IPv6 regex in anonymizer**
