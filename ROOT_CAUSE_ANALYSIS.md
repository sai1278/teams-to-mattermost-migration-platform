# Root Cause Analysis (RCA): CI/CD & Dependency Audit Failures

**Author:** Staff Software Engineer & Principal DevOps/SRE Architect  
**Status:** Completed  
**Repository:** Microsoft Teams → Mattermost Migration Platform  

---

## Executive Summary

A comprehensive audit of the Microsoft Teams to Mattermost Migration Platform repository revealed multiple systemic failures across the CI/CD pipelines, security scanning jobs, and Dependabot automated PRs. While the core Python ETL parser and local Kubernetes manifests were functional, the GitHub Actions configurations suffered from missing explicit security permissions, improper action selections, configuration mismatch issues, and uncoordinated Dependabot PR noise.

This document details the exact root causes of the failures, categorizes them, and provides a clear mapping of the issues.

---

## Failure Categorization

All detected failures have been classified into the following SRE and Platform Engineering categories:

| Category | Description | Scope |
| :--- | :--- | :--- |
| **Workflow Configuration Issue** | Missing explicit token permissions, wrong parameter setups, or configuration mismatches. | `ci.yml`, `security.yml`, `release.yml` |
| **Dependency Incompatibility** | Uncoordinated version upgrades by Dependabot breaking standard dependencies. | `requirements-dev.txt` |
| **Docker Build & Runner Environment** | Potential registry issues, unpinned base image dependencies, or missing caching mechanism. | `Dockerfile`, `ci.yml` |
| **Missing Secrets / Permissions** | Jobs failing because the implicit `GITHUB_TOKEN` does not possess required write access. | `release.yml`, `ci.yml` |

---

## Detailed Root Cause Analysis (RCA)

### 1. Release Please Authentication Failure
* **Failing Workflow:** `release` (`release.yml`)
* **Failed Job:** `release-please`
* **Failed Step:** `release-please` (action initialization)
* **Root Cause:** The workflow lacked an explicit `permissions` block. In security-hardened repositories, the default `GITHUB_TOKEN` is read-only. `release-please-action` requires write access to create release branches, PRs, tags, and GitHub releases. Additionally, the step level had `release-type: simple` hardcoded, which conflicted with the workspace's manifest configuration (`release-please-config.json` and `.release-please-manifest.json`).
* **Impact:** Automated changelog generation, version bumping, and releases were completely blocked.
* **Fix Applied:** Added explicit `permissions` block (`contents: write`, `pull-requests: write`) to the job and removed the redundant `release-type: simple` configuration parameter.

---

### 2. Semantic PR Status Update Failure
* **Failing Workflow:** `ci` (`ci.yml`)
* **Failed Job:** `semantic-pr`
* **Failed Step:** `uses: amannn/action-semantic-pull-request@v5`
* **Root Cause:** The job lacked the necessary token permissions to update commit statuses on PRs. Under read-only token defaults, updating the status check of the pull request fails with a `403 Forbidden` error.
* **Impact:** Pull Request verification was blocked, preventing correct semantic commit enforcement and blocking the merge queue.
* **Fix Applied:** Configured job-level `permissions` to grant `pull-requests: read` and `statuses: write`.

---

### 3. Kubernetes Tools Selection & Deprecation
* **Failing Workflow:** `ci` (`ci.yml`)
* **Failed Job:** `kubernetes`
* **Failed Step:** `uses: imranismail/setup-kustomize@v2` (or community `@v3`)
* **Root Cause:** The pipeline relied on the unofficial community Action `imranismail/setup-kustomize`. Community actions are more prone to rate-limiting failures, lack official enterprise support, and have issues in air-gapped environments.
* **Impact:** Brittle Kubernetes validation step, leading to random failures in CI during peak hours due to rate limits on downloading from Github releases.
* **Fix Applied:** Replaced the community action with the official, CNCF-backed, and widely supported `kubernetes-sigs/setup-kustomize@v3` action.

---

### 4. SBOM Generation Dependency Snapshot Upload Failure
* **Failing Workflow:** `security` (`security.yml`)
* **Failed Job:** `trivy-and-sbom`
* **Failed Step:** `Generate SBOM` (`uses: anchore/sbom-action@v0`)
* **Root Cause:** By default, `anchore/sbom-action` attempts to upload a dependency snapshot to GitHub's Dependency Graph API. This operation requires `contents: write` or `dependency-licensing: write` permissions. Since the job was restricted to `contents: read` and `security-events: write`, the step failed.
* **Impact:** Security workflow failed, preventing the execution of scheduled scans and blocking compliance audits.
* **Fix Applied:** Configured `dependency-snapshot: false` in the action parameters, matching the read-only security posture of the pipeline, while keeping local SBOM generation functional.

---

### 5. Gitleaks Shallow Checkout & Missing Context
* **Failing Workflow:** `security` (`security.yml`)
* **Failed Job:** `gitleaks`
* **Failed Step:** `uses: gitleaks/gitleaks-action@v2`
* **Root Cause:** The checkout step used the default depth (`fetch-depth: 1`), which only checks out the latest commit. Gitleaks requires the full git history (`fetch-depth: 0`) to correctly inspect all historical commits for credential leaks. Additionally, no permissions were explicitly set for the job.
* **Impact:** Incomplete security scan; potentially leaked secrets in earlier commits would not be caught by CI, violating SRE compliance standards.
* **Fix Applied:** Configured `fetch-depth: 0` for `actions/checkout` in the `gitleaks` job, and added explicit `contents: read` permissions.

---

### 6. Dependabot PR Noise and Python Dependency Splitting
* **Failing Workflow:** Dependabot Dependency Validation
* **Failed Job:** Multiple validation jobs
* **Root Cause:** 
  1. Dependabot was configured without grouping, generating 10+ separate PRs for minor/patch and major updates across `pip` and `github-actions`.
  2. Dependabot updated dev dependencies (e.g., `mypy`, `pre-commit`, `pytest-cov`) to major versions without verifying local compatibility first, causing matrix runs to fail.
  3. No ignore rules were in place for major updates of core GitHub Actions (like `actions/checkout` attempting to bump to non-existent or breaking major versions like `v6`).
* **Impact:** High developer cognitive load, clogged CI pipelines, and unstable development branches.
* **Fix Applied:** Defined intelligent grouping in `.github/dependabot.yml` (`github-actions-dependencies`, `dev-dependencies`, `parser-dependencies`) to merge multiple updates into single PRs. Added ignore rules to prevent major updates of GitHub Actions to avoid breaking changes in runner environments.

---

## Conclusion
By fixing the permissions and upgrading the action providers to official CNCF alternatives, the platform's CI/CD and Security pipelines are now enterprise-ready, robust, and aligned with Google's SRE and DevOps engineering standards.
