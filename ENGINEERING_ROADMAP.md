# ENGINEERING ROADMAP
## Teams → Mattermost Migration Platform
**Date:** 2026-06-08  
**Author:** Principal Engineer & Staff SRE, Google  

---

## 1. Roadmap Overview

To address the gaps identified in the [FINAL_GAP_ANALYSIS.md](file:///c:/Users/kanchiDhyana%20sai/.gemini/antigravity/scratch/teams-mattermost-migration/FINAL_GAP_ANALYSIS.md) and bring the platform to enterprise gold-standard compliance, we define a structured, 3-phase roadmap.

```mermaid
gantt
    title Teams -> Mattermost Platform Engineering Roadmap
    dateFormat  YYYY-MM-DD
    section Phase 1: Hardening
    Pin base image digest     :active, p1_1, 2026-06-08, 1d
    Enforce URL SSL           :active, p1_2, after p1_1, 1d
    Atomic Checkpoint writes  :active, p1_3, after p1_2, 1d
    DM member-count guard     :active, p1_4, after p1_3, 1d
    JSONL permission chmod    :active, p1_5, after p1_4, 1d
    section Phase 2: Scale
    Async attachment downloads :descr, p2_1, 2026-06-12, 3d
    JSONL output file splitting:descr, p2_2, after p2_1, 2d
    HMAC anonymization salt   :descr, p2_3, after p2_2, 2d
    Post resume collision fix :descr, p2_4, after p2_3, 2d
    section Phase 3: Resilience
    Distributed checkpoints   :descr, p3_1, 2026-06-25, 7d
    Single-pass ijson parsing :descr, p3_2, after p3_1, 10d
    Airflow orchestration DAGs:descr, p3_3, after p3_2, 5d
```

---

## 2. Phase 1: Security Hardening & Data Integrity Guardrails
**Timeline:** Next 1–2 Sprints | **Target:** Critical & High Severity Gaps

The priority of this phase is to eliminate data loss risks and critical security vulnerabilities so the tool can be safely run inside internal enterprise zones.

### Phase 1 Tasks

#### 1. Pin Docker Base Image Digests
* **Gap Addressed:** SEC-04
* **Effort:** Small (<1 day)
* **Description:** Pin `builder` and `runner` base images to verified SHA256 digests in `apps/parser/Dockerfile`. Prevents silent upstream image substitutions.

#### 2. Enforce SSL Certificate Validation
* **Gap Addressed:** SEC-01
* **Effort:** Small (<1 day)
* **Description:** Modify `application/services.py:336` to create and pass a secure SSL context: `ssl.create_default_context()` to `urllib.request.urlopen`. Prevents MITM attacks during file attachment downloads.

#### 3. Implement Atomic Checkpoint Saves
* **Gap Addressed:** INT-01
* **Effort:** Small (<1 day)
* **Description:** Refactor `MigrationCheckpoint.save()` to write the state to a tempfile (e.g. `.checkpoint.json.tmp`) and then call `os.replace()` to atomically swap the checkpoint file. Eliminates state corruption on OOM/crash.

#### 4. Add DM Member Count Guard
* **Gap Addressed:** INT-03
* **Effort:** Small (<1 day)
* **Description:** Add arity check to `ExportValidationService.validate`: if `len(dc.members) < 2` on any direct channel record, append a validation error and reject the export. Prevents Mattermost bulk import failures.

#### 5. Restrict JSONL Output Permissions
* **Gap Addressed:** SEC-02
* **Effort:** Small (<1 day)
* **Description:** Update CLI wrapper and Makefiles to immediately execute `chmod 600` on generated JSONL output files, preventing unauthorized read access by local system users.

---

## 3. Phase 2: High-Scale & Performance Optimizations
**Timeline:** Next 3–4 Sprints | **Target:** Performance Bottlenecks & Anonymization

This phase resolves execution time bottlenecks and strengthens privacy safeguards for migrations involving millions of posts and hundreds of thousands of attachments.

### Phase 2 Tasks

#### 1. Async Bounded Attachment Downloads
* **Gap Addressed:** SC-02
* **Effort:** Medium (1–3 days)
* **Description:** Refactor the blocking attachment processing queue. Implement an asynchronous pool using `asyncio` or `concurrent.futures.ThreadPoolExecutor` with a strict concurrency limit (e.g., 10 workers) to download files in parallel.

#### 2. JSONL Output Chunking
* **Gap Addressed:** SC-04
* **Effort:** Small (<1 day)
* **Description:** Add a `--max-chunk-mb` argument to the CLI. Update `JsonlFileWriter` to monitor written byte counts and automatically roll over to a new file (e.g., `import_part001.jsonl`, `import_part002.jsonl`) when the threshold is exceeded.

#### 3. HMAC-based Stable Username Anonymization
* **Gap Addressed:** SEC-05
* **Effort:** Medium (1–3 days)
* **Description:** Replace standard `sha1(username)` with `hmac.new(salt, username)` using a cryptographically random migration salt loaded from `TMMP_ANONYMIZE_SALT`. Eliminates local pre-image rainbow table attacks on anonymized outputs.

#### 4. Resolve Post Resume Timestamp Collisions
* **Gap Addressed:** INT-02
* **Effort:** Medium (1–3 days)
* **Description:** Refactor post resume logic to use strict `<` comparison for `timestamp_ms`, and maintain a set of processed post IDs within the last processed millisecond window. Guarantees 100% message preservation.

---

## 4. Phase 3: Resilience & Enterprise Orchestration
**Timeline:** Next 1–2 Quarters | **Target:** Distributed Architecture & Workflow Systems

The final phase moves the platform from a single-node batch utility to a fault-tolerant distributed migration engine suitable for hybrid cloud orchestrators (e.g., Apache Airflow).

### Phase 3 Tasks

#### 1. Distributed Checkpoint Storage
* **Gap Addressed:** OPS-01
* **Effort:** Large (1–2 weeks)
* **Description:** Implement an abstraction layer for checkpoint storage. Support loading and saving checkpoint files to AWS S3/GCS object storage or Redis cluster. Allows Kubernetes Job Pods to resume successfully after being rescheduled to different nodes.

#### 2. Single-Pass ijson Parsing
* **Gap Addressed:** SC-01
* **Effort:** Major (>2 weeks)
* **Description:** Redesign the parser gateway around a single-pass JSON token stream. Dispatch events to validation and transformation routines concurrently, reducing file read operations from 6 down to 1. Reduces network/disk I/O by 83%.

#### 3. Production Apache Airflow Integration
* **Gap Addressed:** Airflow opportunities
* **Effort:** Medium (1–3 days)
* **Description:** Deliver production-ready Apache Airflow DAG templates utilizing KubernetesPodOperator. Automates pre-validation, split parsing, parallel downloads, bulk importing, and post-migration validation checks.
