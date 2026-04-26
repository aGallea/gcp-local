# gcp-local Open-Source Readiness Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the documentation needed to publish `gcp-local` as a public open-source project — a rewritten README, a roadmap, per-service architecture docs, OSS hygiene files (CONTRIBUTING / CODE_OF_CONDUCT / SECURITY / CHANGELOG), GitHub issue + PR templates, and a contributor checklist for adding a new service.

**Architecture:** Pure documentation work — no code changes. New files land in `docs/architecture/`, `docs/development/`, `.github/`, and the repo root. Existing files (`docs/services/{bigquery,gcs}.md`, `docs/deployment.md`, `LICENSE`) are not modified. The README is the only existing file that gets rewritten.

**Tech Stack:** Markdown (GitHub-flavored). No tooling added.

**Spec:** `docs/superpowers/specs/2026-04-26-open-source-readiness-design.md`

**Branch:** `oss-readiness-docs` (created at start of Task 1; the branch was created by the controller in advance — verify with `git branch --show-current`).

**Commit policy:** Commits allowed in this session per the gcp-local feature-branch convention. Use HEREDOC commit messages with the trailer:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## File structure

**New files:**

```
ROADMAP.md
CONTRIBUTING.md
CODE_OF_CONDUCT.md
SECURITY.md
CHANGELOG.md
.github/
  ISSUE_TEMPLATE/
    bug_report.md
    feature_request.md
  pull_request_template.md
docs/
  services/
    secret-manager.md
  architecture/
    overview.md
    bigquery.md
    gcs.md
    secret-manager.md
  development/
    adding-a-service.md
```

**Modified:**

```
README.md   # rewritten
```

**Untouched:**

```
LICENSE
docs/services/{bigquery,gcs}.md
docs/deployment.md
src/, tests/, docker/, scripts/, pyproject.toml
```

---

## Task 1: GitHub templates + SECURITY + CODE_OF_CONDUCT

Goal: land the boilerplate-heavy hygiene files first. Pure additions, no dependencies on other tasks.

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/pull_request_template.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`

- [ ] **Step 1: Verify branch**

Run: `git branch --show-current`
Expected: `oss-readiness-docs`

- [ ] **Step 2: Create `.github/ISSUE_TEMPLATE/bug_report.md`**

```markdown
---
name: Bug report
about: Report unexpected emulator behavior
title: '[bug] '
labels: bug
---

## Service affected

<!-- Which service the bug is in: BigQuery / GCS / Secret Manager / core / other -->

## gcp-local version or commit SHA

<!-- The image tag you ran or `git rev-parse HEAD` from your checkout -->

## Reproduction steps

1.
2.
3.

## Expected behavior

## Actual behavior

## Logs / output

```
<paste relevant logs here>
```
```

- [ ] **Step 3: Create `.github/ISSUE_TEMPLATE/feature_request.md`**

```markdown
---
name: Feature request
about: Request emulation of a real GCP behavior we don't cover yet
title: '[feature] '
labels: enhancement
---

## Service affected

<!-- BigQuery / GCS / Secret Manager / core / other -->

## What real GCP behavior should be emulated

<!-- Link to the relevant Google Cloud documentation -->

## Why it matters / use case

<!-- What workflow is currently blocked or awkward -->

## Proposed approach (optional)

<!-- If you've thought about how this would land in the emulator, sketch it here -->
```

- [ ] **Step 4: Create `.github/pull_request_template.md`**

```markdown
## Summary

<!-- 1–3 bullets describing what this PR does and why -->

## Test plan

- [ ] Relevant unit tests added / updated (`tests/unit/services/<svc>/`)
- [ ] Integration tests pass against the real `google-cloud-<svc>` client (when applicable)
- [ ] `pytest` is green locally
- [ ] `ruff check .` and `ruff format --check .` are clean
- [ ] `mypy src/` is clean

## Documentation checklist (for new services or visible behavior changes)

- [ ] Updated `docs/services/<service>.md` (usage)
- [ ] Updated `docs/architecture/<service>.md` (internals)
- [ ] Updated `README.md` services-at-a-glance table
- [ ] Updated `ROADMAP.md`
- [ ] Updated `docs/deployment.md` ports table (if a new port was added)
- [ ] Added `CHANGELOG.md` entry under `[Unreleased]`

## References

<!-- Links to spec, plan, related issues -->
```

- [ ] **Step 5: Create `SECURITY.md`**

```markdown
# Security policy

`gcp-local` is a local-development emulator for Google Cloud services. It accepts unauthenticated requests by design and is not intended to handle real secrets or production data. The threat model is "developer's local machine" — not a public-facing service.

## Reporting a vulnerability

The preferred channel is **GitHub Security Advisories** on the [`aGallea/gcp-local`](https://github.com/aGallea/gcp-local/security/advisories) repository.

Backup channel: email **asafgallea@gmail.com**.

We acknowledge security reports within **7 days** and aim to release a fix within **30 days** for issues that fall in scope.

## In scope

- Vulnerabilities in code that runs as part of the emulator process: arbitrary code execution, container escape from the published Docker image, sandbox escape from the DuckDB execution engine.
- Path traversal or sandbox escape from the on-disk persistence layer when `PERSIST=1`.
- Vulnerabilities in our build / release pipeline that could be used to compromise users.

## Out of scope

`gcp-local` runs locally and accepts any request. The following are intentional design choices, not vulnerabilities:

- Lack of authentication on emulator endpoints.
- Lack of TLS on emulator ports.
- Predictable / fake resource IDs and tokens (`AnonymousCredentials` works against every endpoint).
- Denial-of-service against an emulator running on a developer's laptop.
- "Information disclosure" of fake data the emulator itself fabricated.

If you are unsure whether something is in scope, file the report — we'd rather triage and explain than miss a real issue.
```

- [ ] **Step 6: Create `CODE_OF_CONDUCT.md`**

Use the verbatim Contributor Covenant 2.1 text. The contact line in the "Enforcement" section must read:

> Instances of abusive, harassing, or otherwise unacceptable behavior may be reported to the community leaders responsible for enforcement at **asafgallea@gmail.com**. All complaints will be reviewed and investigated promptly and fairly.

The full text is the standard 2.1 Contributor Covenant available at https://www.contributor-covenant.org/version/2/1/code_of_conduct/. Paste the entire text verbatim, replace the contact line as above, and save to `CODE_OF_CONDUCT.md`.

- [ ] **Step 7: Verify file structure**

Run:
```bash
ls -1 .github/ISSUE_TEMPLATE/ .github/pull_request_template.md SECURITY.md CODE_OF_CONDUCT.md
```
Expected: each file present, no errors.

- [ ] **Step 8: Commit**

```bash
git add .github/ SECURITY.md CODE_OF_CONDUCT.md
git commit -m "$(cat <<'EOF'
docs: add GitHub templates, SECURITY policy, and Code of Conduct

- .github/ISSUE_TEMPLATE/{bug_report,feature_request}.md — structured
  fields so reports come in with the context we need (affected service,
  version/SHA, repro steps).
- .github/pull_request_template.md — test-plan + doc-update checklists
  matching the procedure in docs/development/adding-a-service.md.
- SECURITY.md — explicit threat model (developer's local machine);
  GitHub Security Advisories preferred channel.
- CODE_OF_CONDUCT.md — Contributor Covenant 2.1 verbatim, contact email
  asafgallea@gmail.com.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: CHANGELOG.md (backfilled)

Goal: a Keep-a-Changelog-formatted CHANGELOG with the existing PRs #1–#5 backfilled under a single `0.1.0-alpha` entry, plus an empty `[Unreleased]` section ready for future PRs.

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Create `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to `gcp-local` are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once a 1.0 release is cut.

Add new entries under `[Unreleased]` as part of every PR that changes user-visible behavior. Promote `[Unreleased]` to a versioned section when cutting a release.

## [Unreleased]

(empty)

## [0.1.0-alpha] — 2026-04-26

The initial alpha covers three of the planned v1 services (BigQuery, GCS, Secret Manager) plus the cross-service core framework. No git tag is cut at this point — `0.1.0-alpha` is a backfill anchor for the documentation work that prepares the repo for open-sourcing.

### Added

- **Core framework** — `Service` protocol, `ServiceRegistry` with entry-point discovery (`gcp_local.services` group), admin API on port 4510 (`/_emulator/{health,services,reset}`), per-service port overrides via `<SERVICE>_EMULATOR_PORT`, in-memory and disk-backed (`PERSIST=1`) storage modes.
- **BigQuery service (port 9050, REST)** — dataset/table CRUD; query (`jobs.insert` and synchronous `jobs.query`); DML (`INSERT` / `UPDATE` / `DELETE` / `MERGE`); streaming inserts (`tabledata.insertAll`); `INFORMATION_SCHEMA.{TABLES,COLUMNS,SCHEMATA}`; inline NDJSON + CSV load jobs over multipart and resumable upload protocols, with full `writeDisposition` (APPEND / TRUNCATE / EMPTY) and `createDisposition` (IF_NEEDED / NEVER) and schema autodetect for both source formats. Backed by an embedded DuckDB engine with `sqlglot` BigQuery → DuckDB translation. (PRs [#2](https://github.com/aGallea/gcp-local/pull/2), [#4](https://github.com/aGallea/gcp-local/pull/4), [#5](https://github.com/aGallea/gcp-local/pull/5).)
- **GCS service (port 4443, REST)** — bucket and object CRUD, multipart and resumable uploads, signed-URL accept-and-ignore.
- **Secret Manager service (port 8086, gRPC)** — secret and version CRUD, payload access by name + version, IAM accept-and-ignore.
- **Docker image** — `python:3.13-slim` based, `docker/Dockerfile` plus deployment guide (`docs/deployment.md`) covering Docker, docker-compose, Kubernetes, and Rancher Desktop. (PR [#3](https://github.com/aGallea/gcp-local/pull/3).)
- **User-facing usage docs** — `docs/services/{bigquery,gcs}.md` walking through connection, examples, and per-service emulation gaps.

### Known limitations

- BigQuery load jobs accept inline payloads only (NDJSON / CSV). `gs://` source URIs and binary formats (Parquet / Avro / ORC) are not yet supported.
- BigQuery `statistics.totalBytesProcessed` always reports `0` — DuckDB does not expose an equivalent metric.
- BigQuery `maxBadRecords` and `ignoreUnknownValues` on load jobs are accepted but treated as all-or-nothing (one bad row aborts the job).
- BigQuery DATE / TIMESTAMP / JSON column coercion in CSV load jobs is pass-through; the emulator relies on DuckDB's implicit cast.
- Authentication is not enforced on any service; clients must use `AnonymousCredentials`.

[Unreleased]: https://github.com/aGallea/gcp-local/compare/main...HEAD
[0.1.0-alpha]: https://github.com/aGallea/gcp-local/releases/tag/v0.1.0-alpha
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs: add CHANGELOG.md (Keep-a-Changelog) backfilled with PRs #1–#5

Single 0.1.0-alpha entry pinned to 2026-04-26 (the date PR #5 merged)
captures the BigQuery, GCS, and Secret Manager services plus the core
framework, with a Known Limitations subsection that mirrors the
follow-ups tracked in ROADMAP.md.

[Unreleased] section is the slot for future PR entries; the contributor
template (PR template + adding-a-service checklist) directs every PR to
add an entry there.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Create `CONTRIBUTING.md`**

```markdown
# Contributing to gcp-local

Thanks for your interest in contributing! This document covers local development setup, the PR workflow, and conventions specific to this project.

If you're adding a brand-new service (Pub/Sub, Firestore, etc.), read [`docs/development/adding-a-service.md`](docs/development/adding-a-service.md) first — that walks through every file you'll need to touch.

## Local development setup

Requirements:

- Python 3.13
- A POSIX-y shell (macOS or Linux). Windows users can use WSL2.
- Docker (optional, only needed if you want to test the container image)

Clone and install:

```bash
git clone https://github.com/aGallea/gcp-local.git
cd gcp-local
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the emulator from your checkout:

```bash
python -m gcp_local
```

Health check:

```bash
curl http://localhost:4510/_emulator/health
```

## Running the test suite

Unit tests (fast, no network):

```bash
python -m pytest tests/unit -v
```

Integration tests (drive the real `google-cloud-*` clients against an in-process emulator):

```bash
python -m pytest tests/integration -v
```

Lint and type-check:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src/
```

CI runs the same commands; if they pass locally they should pass in CI.

## Branch + PR workflow

1. Create a feature branch off `master`. Branch names use the form `<service>` or `<service>-<topic>`, e.g. `bigquery-load-jobs` or `pubsub`.
2. Push the branch and open a pull request to `master`.
3. Fill out the PR template (`.github/pull_request_template.md`) — including the doc-update checklist if your PR adds or changes user-visible behavior.
4. CI must be green before merge.
5. We squash-merge to `master`. Delete the branch after merge (the PR UI offers this with one click).

## Commit message conventions

Existing commits follow the `<type>(<scope>): <subject>` form. Reuse it. Recognized types:

| Type | Use for |
|---|---|
| `feat` | A new user-visible feature |
| `fix` | A bug fix |
| `refactor` | Code change without user-visible behavior change |
| `perf` | Performance improvement without behavior change |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `chore` | Build / tooling / repo housekeeping |

Scope is the service name when the change is scoped to one service (`feat(bigquery): ...`). Use `core` for cross-cutting framework changes, or omit the scope when it would feel forced.

The PR title becomes the squash-merge commit subject, so the same convention applies to PR titles.

## Adding a new service

See [`docs/development/adding-a-service.md`](docs/development/adding-a-service.md) for the full checklist. Highlights:

- Brainstorm a spec → save to `docs/superpowers/specs/`.
- Write a TDD plan → save to `docs/superpowers/plans/`.
- Implement the service under `src/gcp_local/services/<service>/`.
- Register the service via the `gcp_local.services` entry point in `pyproject.toml`.
- Cover with both unit and integration tests.
- Update the docs listed in the PR template's checklist.

## Reporting bugs and requesting features

Use the GitHub issue templates at [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/). They prompt you for the context we need to triage quickly.

## Reporting security issues

See [`SECURITY.md`](SECURITY.md). The TL;DR is: GitHub Security Advisories preferred, `asafgallea@gmail.com` as the backup channel.

## Code of conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). By participating you agree to abide by its terms.
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "$(cat <<'EOF'
docs: add CONTRIBUTING.md

Documents local dev setup (venv + pip install -e .[dev]), the test
suite (unit / integration / ruff / mypy), branch + PR workflow,
commit message conventions, and pointers to the new-service checklist,
issue templates, security policy, and code of conduct.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: docs/services/secret-manager.md (USAGE)

Goal: the user-facing usage doc for Secret Manager, mirroring the structure of `docs/services/{bigquery,gcs}.md`.

**Files:**
- Create: `docs/services/secret-manager.md`

- [ ] **Step 1: Read existing usage docs to match style**

Read both `docs/services/bigquery.md` and `docs/services/gcs.md` end-to-end to internalize tone, section ordering, and example shape. The new file should feel like a sibling.

- [ ] **Step 2: Read the Secret Manager spec for the emulation scope**

Read `docs/superpowers/specs/2026-04-24-gcp-local-secret-manager-design.md` to enumerate what's emulated, what's accepted-and-ignored, and what's out of scope. This is the source of truth for the "What's emulated" and "What's not emulated" sections.

- [ ] **Step 3: Read the implementation to confirm details**

Skim `src/gcp_local/services/secret_manager/{service.py,servicer.py,models.py,storage.py,names.py}` to confirm port, transport, resource-name format, and any quirks that differ from the spec.

- [ ] **Step 4: Write `docs/services/secret-manager.md`**

The file follows this structure (same as `docs/services/bigquery.md`):

1. **Title + one-paragraph elevator pitch** — what GCP API we're emulating, that the official `google-cloud-secret-manager` client works unchanged. State the default port (8086) and that the wire protocol is gRPC (no `*_EMULATOR_HOST` env var; clients connect via `client_options.api_endpoint`).

2. **What's emulated** — bullet list. From the v1 spec, this is at least:
   - Secret lifecycle (`CreateSecret`, `GetSecret`, `ListSecrets`, `UpdateSecret`, `DeleteSecret`)
   - Version lifecycle (`AddSecretVersion`, `GetSecretVersion`, `AccessSecretVersion`, `ListSecretVersions`, `DisableSecretVersion`, `EnableSecretVersion`, `DestroySecretVersion`)
   - Resource-name validation (`projects/<project>/secrets/<id>` and `projects/<project>/secrets/<id>/versions/<n>`; `latest` alias on `Access`)
   - Project namespacing (different projects are isolated)
   - In-memory and on-disk storage backends (`PERSIST=1`)

3. **What's not emulated (v1)** — bullet list. Pull from the spec:
   - Replication policy (`automatic` accepted, `user_managed` accepted but not enforced)
   - IAM (`SetIamPolicy` / `GetIamPolicy` accepted and stubbed; no real ACL enforcement)
   - Customer-managed encryption keys (CMEK) — accepted, not enforced
   - Rotation schedules
   - Annotations & labels — round-tripped, not validated
   - Audit logging
   - Real cryptographic guarantees (payloads stored in cleartext)

4. **Connecting** — Python client snippet. Secret Manager has no `*_EMULATOR_HOST` env var; show the `client_options` form:

   ```python
   from google.api_core import client_options as co
   from google.auth import credentials as ga_credentials
   from google.cloud import secretmanager

   client = secretmanager.SecretManagerServiceClient(
       credentials=ga_credentials.AnonymousCredentials(),
       client_options=co.ClientOptions(
           api_endpoint="localhost:8086",
       ),
       transport="grpc",
   )
   ```

   Note that `transport="grpc"` is required — the gRPC client picks insecure-channel automatically when `api_endpoint` points at a non-TLS host.

5. **Examples** — five short snippets matching the operations callers actually use:
   1. Create a secret (`CreateSecret` with automatic replication).
   2. Add a version (`AddSecretVersion` with payload).
   3. Access a version by `latest` and by explicit number.
   4. List versions for a secret.
   5. Delete a secret (with `delete_contents` semantics).

6. **Limits & quirks** — call out anything callers should know:
   - No real authentication; any caller can read any secret (it's a local emulator).
   - Payloads are stored verbatim — no CMEK, no envelope encryption.
   - `Access` returns the same payload for all callers; there's no replica routing.
   - `state` transitions (`ENABLED` / `DISABLED` / `DESTROYED`) are honored on `Access`.
   - Resource-name validation is loose (per the spec's project-name handling).

Aim for a similar length and depth as `docs/services/bigquery.md` and `docs/services/gcs.md`. The result should be ~250–400 lines of Markdown.

- [ ] **Step 5: Verify the file renders**

Inspect the file: every code fence is closed, every relative link resolves to an existing path, no leftover TODO markers.

- [ ] **Step 6: Commit**

```bash
git add docs/services/secret-manager.md
git commit -m "$(cat <<'EOF'
docs(secret-manager): user-facing usage guide

Adds docs/services/secret-manager.md covering the full secret + version
lifecycle the emulator supports, what's accepted-and-ignored (IAM, CMEK,
rotation, replication policy enforcement, audit logging), how to
connect with the official Python client via client_options.api_endpoint
(no *_EMULATOR_HOST env var for Secret Manager), and the limits/quirks
callers should be aware of (no auth, payloads in cleartext, etc.).

Mirrors the structure already used by docs/services/{bigquery,gcs}.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: docs/architecture/overview.md

Goal: the cross-cutting architecture doc that every per-service architecture doc links into.

**Files:**
- Create: `docs/architecture/overview.md`

- [ ] **Step 1: Read core modules to ensure accuracy**

Read each of:
- `src/gcp_local/core/service.py` — the `Service` protocol, `Port`, `HealthStatus`.
- `src/gcp_local/core/registry.py` — `ServiceRegistry`, entry-point discovery.
- `src/gcp_local/core/context.py` — the `Context` dataclass and what it carries.
- `src/gcp_local/core/state_hub.py` — the `StateHub` event bus.
- `src/gcp_local/core/admin_api.py` — the `/_emulator/...` admin endpoints.
- `src/gcp_local/core/lifecycle.py` — startup / shutdown sequencing.
- `src/gcp_local/core/storage.py` — anything cross-cutting about persistence.
- `src/gcp_local/core/errors.py` — base error envelope helpers.
- `pyproject.toml` — the `[project.entry-points."gcp_local.services"]` table.
- `src/gcp_local/__main__.py` and `src/gcp_local/cli.py` (if they exist) — how the CLI bootstraps.

- [ ] **Step 2: Write `docs/architecture/overview.md`**

Section structure (use these headings verbatim):

```
# gcp-local internals — overview

## Audience

## Repository tour

## Service protocol

## Service registry

## Lifecycle

## Admin API

## Port overrides

## Persistence

## State hub

## Common patterns

## Generated proto stubs
```

Per-section content requirements:

- **Audience** (~80 words) — one-paragraph statement that this doc is for someone modifying the emulator's internals (not for users of the emulator). Pointers: usage docs at `docs/services/`, deployment at `docs/deployment.md`.
- **Repository tour** (~150 words, one paragraph per top-level dir) — `src/gcp_local/core/` (framework), `src/gcp_local/services/` (per-service implementations), `src/gcp_local/generated/` (vendored proto stubs), `tests/{unit,integration}/`, `docs/`, `docker/`, `scripts/`. Each paragraph names the most-touched files.
- **Service protocol** (~150 words) — quote the `Service` protocol from `src/gcp_local/core/service.py` (name, default_ports, async start/stop/reset_state, sync health). Explain `Port(number, protocol)` and `HealthStatus(ok, message)`. Note that everything else (FastAPI app, gRPC server, sweeper tasks) lives behind this interface, so the framework doesn't need to know whether the service is REST or gRPC.
- **Service registry** (~120 words) — explain `ServiceRegistry`: programmatic `register()` for tests, entry-point discovery via the `gcp_local.services` group in `pyproject.toml`. Show the entry-point block as it currently exists (read from `pyproject.toml`). Mention that the CLI (or test fixtures) load all entry-points and instantiate the requested subset based on the `SERVICES` env var.
- **Lifecycle** (~150 words) — sequence of `start()` calls (services start concurrently), how `Context` is constructed once and shared, how `stop()` is called on Ctrl-C / SIGTERM, what `reset_state()` does (drops in-memory state, recreates on-disk state); contrast with the admin API's `/reset` endpoint.
- **Admin API** (~120 words) — the three endpoints on port 4510: `/_emulator/health` (returns each service's `HealthStatus`), `/_emulator/services` (registry view), `/_emulator/reset?service=<name>` (calls `reset_state()` on one service). Show one example response per endpoint.
- **Port overrides** (~100 words) — the `<SERVICE>_EMULATOR_PORT` env var convention; how the CLI assembles `Context.port_overrides`; what happens when a service has multiple ports.
- **Persistence** (~120 words) — `PERSIST=1` switches storage from in-memory to on-disk under `/data` (the path is conventional, set by the Dockerfile's `VOLUME` directive). Per-service implementations decide whether/how to honor `PERSIST` (BigQuery uses a single DuckDB file; GCS uses an object directory; Secret Manager uses a JSON catalog). Restart semantics are documented per-service.
- **State hub** (~80 words) — the `StateHub` is currently lightweight infrastructure for cross-service notifications. It is reserved for future cross-service work (e.g., GCS → BQ load notifications). No service emits events today.
- **Common patterns** (~150 words) — REST error envelope shape (`{"error": {"code", "message", "errors": [{reason, message, domain}], "status"}}`); the `make_error_response` / `bigquery_error_response`-style helpers per service; AnonymousCredentials posture (no auth enforced anywhere); resource-name validation conventions; in-memory vs disk-backed storage protocol shape.
- **Generated proto stubs** (~80 words) — vendor-and-commit pattern: stubs live under `src/gcp_local/generated/`, regenerated via `scripts/gen_protos.sh`. Reasoning: keeps the build hermetic, avoids needing `protoc` at install time, makes diffs reviewable.

Total expected length: ~1200–1500 words (~300–400 lines of Markdown).

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/overview.md
git commit -m "$(cat <<'EOF'
docs(architecture): add cross-cutting overview

Documents the framework that the per-service implementations sit on:
- Service protocol + Port + HealthStatus contract
- Registry (programmatic register + entry-point discovery)
- Lifecycle (start / stop / reset_state) and the Context object
- Admin API on port 4510 (health, services, reset)
- Port-override convention (<SERVICE>_EMULATOR_PORT)
- Persistence (PERSIST=1) and the per-service split
- StateHub (reserved cross-service event bus)
- REST error envelope + AnonymousCredentials posture
- Vendor-and-commit pattern for proto stubs

Linked from each docs/architecture/<service>.md to avoid repeating the
framework details in every per-service file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: docs/architecture/bigquery.md

Goal: the BigQuery internals deep-dive.

**Files:**
- Create: `docs/architecture/bigquery.md`

- [ ] **Step 1: Read the BigQuery service code**

Read each of:
- `src/gcp_local/services/bigquery/service.py`
- `src/gcp_local/services/bigquery/app.py`
- `src/gcp_local/services/bigquery/models.py`
- `src/gcp_local/services/bigquery/storage.py`
- `src/gcp_local/services/bigquery/names.py`
- `src/gcp_local/services/bigquery/types.py`
- `src/gcp_local/services/bigquery/errors.py`
- `src/gcp_local/services/bigquery/engine/connection.py`
- `src/gcp_local/services/bigquery/engine/jobs.py` (`JobRunner`)
- `src/gcp_local/services/bigquery/engine/loads.py` (`LoadRunner`)
- `src/gcp_local/services/bigquery/engine/translate.py`
- `src/gcp_local/services/bigquery/engine/shims.py`
- `src/gcp_local/services/bigquery/engine/info_schema.py`
- `src/gcp_local/services/bigquery/engine/autodetect.py`
- `src/gcp_local/services/bigquery/engine/coerce.py`
- `src/gcp_local/services/bigquery/engine/resumable.py`
- `src/gcp_local/services/bigquery/engine/_time.py`
- `src/gcp_local/services/bigquery/routes/{datasets,tables,jobs,tabledata,uploads}.py`

- [ ] **Step 2: Read the relevant specs for design rationale**

Read both:
- `docs/superpowers/specs/2026-04-25-gcp-local-bigquery-design.md`
- `docs/superpowers/specs/2026-04-26-gcp-local-bigquery-load-jobs-design.md`

- [ ] **Step 3: Write `docs/architecture/bigquery.md`**

Section structure (use verbatim):

```
# BigQuery — internals

## At a glance

## Wire & port

## Storage model

## Catalog vs DuckDB

## Type mapping

## Request lifecycle: SELECT query

## SQL translation

## DuckDB shims (UDFs)

## Streaming inserts (`tabledata.insertAll`)

## Load jobs

## INFORMATION_SCHEMA

## Job records and TTL

## Errors

## Tests

## Internals-level limitations
```

Per-section content requirements:

- **At a glance** (~120 words) — one-paragraph summary; what user-visible behavior is emulated, link to `docs/services/bigquery.md` for that. Tech stack: DuckDB embedded engine + sqlglot translation. Ack: not a real BigQuery (no real cost/quota model, single execution lane).
- **Wire & port** (~80 words) — REST on 9050; `BIGQUERY_EMULATOR_HOST` env var; admin port 4510 unchanged.
- **Storage model** (~150 words) — single DuckDB file (in-memory by default, on-disk under `/data/bigquery.duckdb` when `PERSIST=1`); schema-name encoding `"<project>:<dataset>"` (with the `:` separator chosen because BQ project IDs don't allow `:`); `_gcp_local_meta` for catalog rows; `_gcp_local_jobs` for transient query result tables.
- **Catalog vs DuckDB** (~120 words) — why we keep an explicit catalog (`_gcp_local_meta.tables` / `.datasets`) on top of DuckDB's own `information_schema`: BQ field modes (REQUIRED / NULLABLE / REPEATED), partitioning config, labels, RFC3339 timestamps. The catalog is the source of truth for fields DuckDB doesn't preserve.
- **Type mapping** (~150 words) — table BQ → DuckDB (`STRING`→`VARCHAR`, `INT64`→`BIGINT`, `FLOAT64`→`DOUBLE`, `BOOL`→`BOOLEAN`, `NUMERIC`→`DECIMAL(38,9)`, `TIMESTAMP`→`TIMESTAMP WITH TIME ZONE`, `DATETIME`→`TIMESTAMP`, `JSON`→`JSON`, `RECORD`→`STRUCT(...)`, `ARRAY<T>`→`T[]`); rejected types (`GEOGRAPHY` / `INTERVAL` / `RANGE`); the `TIMESTAMP` vs `DATETIME` round-trip (catalog stores BQ-declared type, used at row serialization time).
- **Request lifecycle: SELECT query** (~250 words) — trace `client.query("SELECT ...")` end-to-end:
  1. POST → `routes/jobs.py::insert_job` (or `query_sync` for the synchronous path)
  2. → `JobRunner.run_query(project, job_id, sql)`
  3. → `engine/translate.py::translate(sql, catalog)` — sqlglot dialect=bigquery parse, AST passes (3-part-name rewrite, wildcard expansion, `SAFE.<fn>` → `TRY(<fn>)`, INFORMATION_SCHEMA resolution, partitioning DDL strip), then `node.sql(dialect="duckdb")`
  4. → `BigQueryConnection.execute(translated)` — runs in a single-threaded executor
  5. SELECT path: materialize results into `_gcp_local_jobs._job_<job_id>`, capture schema from sqlglot analyzer + catalog
  6. Build `JobRecord` (state=DONE, statistics populated)
  7. Response: serialize via `routes/jobs.py::job_to_api`. Pagination via base64-encoded offset tokens.
- **SQL translation** (~200 words) — sqlglot pipeline: parse → AST passes → emit DuckDB. List the AST passes with their current behavior (read from `engine/translate.py`). Note the legacy-SQL rejection (`useLegacySql: true` → `INVALID_QUERY`) and that `ML.*` / `ST_*` / scripting are not supported.
- **DuckDB shims (UDFs)** (~150 words) — list of registered shims from `engine/shims.py` (`GENERATE_UUID`, `FORMAT_DATE`, `FORMAT_TIMESTAMP`, `PARSE_DATE`, `PARSE_TIMESTAMP`, `APPROX_QUANTILES`, etc.). Distinguish AST-rewritten functions (`SAFE_CAST` → `TRY_CAST`) from runtime UDFs (`GENERATE_UUID`).
- **Streaming inserts** (~150 words) — `routes/tabledata.py::insertAll` flow: validate rows against `TableRecord.schema` (via `engine/coerce.py`), batched `INSERT INTO ... VALUES`, JSON-column coercion (dict/list → JSON string server-side). Mention `skipInvalidRows` semantics and the `insertErrors[]` response shape. Streaming buffer is not simulated (rows are immediately visible).
- **Load jobs** (~250 words) — `routes/uploads.py` + `engine/loads.py`:
  - URL surface (`/upload/bigquery/v2/projects/{p}/jobs?uploadType={multipart,resumable}`), PUT/DELETE for resumable
  - Multipart parsing via stdlib `email.parser` (compat API; not `policy.default` because the latter breaks binary payloads)
  - Resumable session storage (`engine/resumable.py::ResumableSessionStore`) with TTL-swept in-memory dict
  - `LoadRunner` flow: parse data → resolve schema (explicit / autodetect / existing-table / error) → enforce `createDisposition` → apply `writeDisposition` (`WRITE_TRUNCATE` is wrapped in `BEGIN/COMMIT` for transactionality) → batched INSERT
  - Source-format support: NDJSON + CSV (`engine/autodetect.py` infers schema for both)
  - `LOAD` job type lands in the same job dict as QUERY/DML via `JobRunner.register_external`
- **INFORMATION_SCHEMA** (~100 words) — virtual views resolved at translate time (`engine/info_schema.py`) — TABLES, COLUMNS, SCHEMATA — rewritten to SELECTs over `_gcp_local_meta`. Unsupported views (`JOBS_BY_*`, `PARTITIONS`, etc.) emit `invalidQuery`.
- **Job records and TTL** (~100 words) — in-memory map keyed by `(project, job_id)`; 1-hour TTL swept every 5 minutes (`JobRunner.sweep_expired`). Job state always `DONE` (no async execution); `cancel` is a no-op success.
- **Errors** (~150 words) — REST envelope shape, status mapping (table from `errors.py`: `DatasetNotFound`/`TableNotFound`/`JobNotFound` → 404 `notFound`; `*AlreadyExists` → 409 `duplicate`; `InvalidName` / `UnsupportedType` / `InvalidValue` → 400 `invalid`; `InvalidQuery` → 400 `invalidQuery`; uncaught → 500 `internalError`). Note the special handling for query-execution errors: the HTTP response is 200 with `errorResult` populated (matches real BQ). Mention `make_error_response` for ad-hoc envelope construction.
- **Tests** (~120 words) — unit test layout under `tests/unit/services/bigquery/` — one file per concern (`test_routes_*.py`, `test_engine_*.py`, `test_storage.py`, etc.); integration tests at `tests/integration/test_bigquery_integration.py` driving real `google-cloud-bigquery` end-to-end including the resumable upload path with a ~6 MiB synthetic payload.
- **Internals-level limitations** (~150 words) — the gap list:
  - Single DuckDB connection serializes all execution
  - `statistics.totalBytesProcessed` always `0`
  - GCS-URI loads not implemented (`gs://` source URIs)
  - Parquet / Avro / ORC source formats not implemented
  - `maxBadRecords` / `ignoreUnknownValues` accepted but treated as all-or-nothing
  - DATE/TIMESTAMP/JSON CSV cell coercion pass-through (relies on DuckDB implicit cast)
  - Time-zone handling: DuckDB stores TIMESTAMPs in UTC, no client-side TZ shifting
  - Job records and result temp tables not persisted across restarts (only datasets/tables/data are)
  - `cancel` is a no-op (queries run synchronously)

Total expected length: ~2000–2500 words (~500–650 lines of Markdown).

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/bigquery.md
git commit -m "$(cat <<'EOF'
docs(architecture): BigQuery internals deep-dive

Documents the DuckDB-backed BigQuery emulator end-to-end:
- Wire (REST :9050) and storage model (single DuckDB file with project-
  scoped schemas + the _gcp_local_meta catalog)
- Type mapping (BQ ↔ DuckDB), incl. the TIMESTAMP/DATETIME round-trip
- Request lifecycle for a SELECT query through sqlglot translation,
  AST passes, and result materialization in _gcp_local_jobs
- DuckDB UDF + AST-rewrite shims (GENERATE_UUID, FORMAT_DATE, SAFE.→TRY)
- Streaming inserts (tabledata.insertAll) and load jobs (multipart +
  resumable, NDJSON + CSV, transactional WRITE_TRUNCATE)
- INFORMATION_SCHEMA resolution
- Job records, TTL sweep, and error envelope mapping
- Internals-level limitations (single-connection serialization,
  totalBytesProcessed=0, no GCS-URI loads yet, etc.)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: docs/architecture/gcs.md

Goal: GCS internals deep-dive.

**Files:**
- Create: `docs/architecture/gcs.md`

- [ ] **Step 1: Read the GCS service code**

Read each of:
- `src/gcp_local/services/gcs/service.py`
- `src/gcp_local/services/gcs/models.py`
- `src/gcp_local/services/gcs/storage.py`
- `src/gcp_local/services/gcs/preconditions.py`
- `src/gcp_local/services/gcs/events.py`
- `src/gcp_local/services/gcs/ids.py`
- `src/gcp_local/services/gcs/errors.py`
- All files under `src/gcp_local/services/gcs/routes/`

- [ ] **Step 2: Read the GCS spec**

Read `docs/superpowers/specs/2026-04-24-gcp-local-gcs-design.md` for design rationale.

- [ ] **Step 3: Write `docs/architecture/gcs.md`**

Section structure (use verbatim):

```
# GCS — internals

## At a glance

## Wire & port

## Storage model

## Object representation

## Request lifecycle: simple upload

## Resumable uploads

## Composite operations

## Preconditions

## Signed URLs

## Notifications and events

## Errors

## Tests

## Internals-level limitations
```

Per-section content requirements:

- **At a glance** (~120 words) — one-paragraph summary, link to `docs/services/gcs.md` for usage. Pure REST emulator, in-memory + on-disk storage, no DuckDB.
- **Wire & port** (~60 words) — REST on 4443; `STORAGE_EMULATOR_HOST` env var; admin port 4510.
- **Storage model** (~200 words) — bucket as a directory (when `PERSIST=1`); object as a file plus a metadata sidecar JSON. In-memory backend uses dicts keyed by `(bucket, object_name, generation)`. Reference the file paths from `storage.py`. Note generations and metageneration counters are first-class (used by `If-Match` / `If-None-Match` preconditions).
- **Object representation** (~150 words) — what's stored per object: bytes payload, `Content-Type`, user metadata (`x-goog-meta-*`), CRC32C checksum, MD5 hash, generation, metageneration, time-created, time-updated. Show the JSON shape that the API returns (one example).
- **Request lifecycle: simple upload** (~200 words) — trace `client.upload_blob(...)` (single-shot) through the route, validate-and-coerce, write-to-storage, response shape.
- **Resumable uploads** (~200 words) — multi-stage flow: init POST returns `Location` URL → PUT chunks honoring `Content-Range` → completion. Session state (in-memory or persisted), TTL.
- **Composite operations** (~120 words) — `compose` / `copy` / `rewrite` semantics; how they're modeled (rewrite-with-token for chunked rewrites).
- **Preconditions** (~150 words) — `ifGenerationMatch` / `ifGenerationNotMatch` / `ifMetagenerationMatch` / `ifMetagenerationNotMatch` enforced via `preconditions.py`. Pre-flight check vs post-write check.
- **Signed URLs** (~100 words) — accept-and-redirect: signed URLs from real GCS get rewritten to point at the emulator. We don't validate signatures (no real key infrastructure). Document the `&x-goog-signature=...` accept-and-ignore behavior.
- **Notifications and events** (~80 words) — `events.py`'s role: today this is a placeholder for cross-service notifications (e.g., GCS → BQ load triggers). No external delivery yet.
- **Errors** (~100 words) — REST envelope shape (matches GCP standard). Map `BucketNotFound` / `ObjectNotFound` → 404; precondition failures → 412; quota errors are not enforced.
- **Tests** (~100 words) — unit test layout, integration tests in `tests/integration/test_gcs_integration.py` driving real `google-cloud-storage`.
- **Internals-level limitations** (~120 words) — pull from `docs/services/gcs.md`'s "What's not emulated" plus internals-level gaps (no IAM, no real signing, no actual GCS↔BQ wiring even though `events.py` is in place).

Total expected length: ~1500–1800 words (~400–500 lines of Markdown).

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/gcs.md
git commit -m "$(cat <<'EOF'
docs(architecture): GCS internals deep-dive

Documents the REST-on-4443 GCS emulator: bucket-as-directory + object
file + sidecar JSON storage model, generation/metageneration tracking,
simple + resumable upload flows, composite ops (compose / copy / rewrite),
preconditions enforcement, signed-URL accept-and-ignore behavior, and
the cross-service event placeholder (events.py) that future GCS→BQ
load-job wiring will hook into.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: docs/architecture/secret-manager.md

Goal: Secret Manager internals deep-dive.

**Files:**
- Create: `docs/architecture/secret-manager.md`

- [ ] **Step 1: Read the Secret Manager service code**

Read each of:
- `src/gcp_local/services/secret_manager/service.py`
- `src/gcp_local/services/secret_manager/servicer.py` (the gRPC handler implementation)
- `src/gcp_local/services/secret_manager/models.py`
- `src/gcp_local/services/secret_manager/storage.py`
- `src/gcp_local/services/secret_manager/names.py`
- The vendored proto stubs under `src/gcp_local/generated/google/cloud/secretmanager/`

- [ ] **Step 2: Read the spec**

Read `docs/superpowers/specs/2026-04-24-gcp-local-secret-manager-design.md`.

- [ ] **Step 3: Write `docs/architecture/secret-manager.md`**

Section structure (verbatim):

```
# Secret Manager — internals

## At a glance

## Wire & port

## gRPC server setup

## Vendored proto stubs

## Storage model

## Resource names

## Request lifecycle: AccessSecretVersion

## Version state machine

## IAM policy stubs

## Errors

## Tests

## Internals-level limitations
```

Per-section content requirements:

- **At a glance** (~120 words) — one-paragraph summary, link to `docs/services/secret-manager.md`. Pure gRPC service, in-memory or JSON-on-disk catalog.
- **Wire & port** (~80 words) — gRPC on 8086; no `*_EMULATOR_HOST` env var (clients connect via `client_options.api_endpoint` + `transport="grpc"`); admin port 4510.
- **gRPC server setup** (~120 words) — `grpc.aio.server()`, the `SecretManagerServiceServicer` from `servicer.py`, how it's wired to the `Service` lifecycle (`start` builds the server, `stop` calls `server.stop(grace=...)`). Where the service registers with the registry.
- **Vendored proto stubs** (~120 words) — stubs live under `src/gcp_local/generated/google/cloud/secretmanager/`; regen via `scripts/gen_protos.sh`. Reasoning: keeps the build hermetic, no `protoc` at install time, diffs reviewable. Mention the upstream proto source.
- **Storage model** (~150 words) — in-memory dicts keyed by `(project, secret_id)` and `(project, secret_id, version_number)`; on-disk variant under `/data/secret_manager/` is a single JSON file per project. Reference `storage.py`.
- **Resource names** (~120 words) — `projects/<project>/secrets/<id>` and `projects/<project>/secrets/<id>/versions/<n>`; `latest` alias resolution at `Access` time; validation rules (read from `names.py`).
- **Request lifecycle: AccessSecretVersion** (~150 words) — trace the most representative call: gRPC → servicer method → catalog lookup → state check (DESTROYED → 404 / not-found, DISABLED → 400) → return payload.
- **Version state machine** (~120 words) — ENABLED → DISABLED ↔ ENABLED → DESTROYED (terminal). State transitions on `EnableSecretVersion` / `DisableSecretVersion` / `DestroySecretVersion`; what happens to payload bytes on DESTROYED (zeroed).
- **IAM policy stubs** (~80 words) — `SetIamPolicy` / `GetIamPolicy` accepted, round-tripped, but never enforced. Round-trip fidelity is the only guarantee.
- **Errors** (~100 words) — gRPC status codes used: `NOT_FOUND` for missing secrets/versions; `ALREADY_EXISTS` for duplicate creates; `INVALID_ARGUMENT` for malformed names; `FAILED_PRECONDITION` for state-machine violations on terminal versions.
- **Tests** (~100 words) — unit tests under `tests/unit/services/secret_manager/`; integration tests at `tests/integration/test_secret_manager_integration.py` driving real `google-cloud-secret-manager`.
- **Internals-level limitations** (~120 words) — no real auth (any caller reads any secret), payloads stored in cleartext, no CMEK enforcement, no rotation schedules, no replication routing, IAM stubbed not enforced, no audit logging.

Total expected length: ~1300–1600 words (~350–450 lines of Markdown).

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/secret-manager.md
git commit -m "$(cat <<'EOF'
docs(architecture): Secret Manager internals deep-dive

Documents the gRPC-on-8086 Secret Manager emulator: how the gRPC server
hooks into the Service lifecycle, the vendored proto stubs (regen via
scripts/gen_protos.sh), the in-memory + on-disk storage model, resource-
name validation, the version state machine (ENABLED/DISABLED/DESTROYED),
the request lifecycle for AccessSecretVersion, and the accepted-but-not-
enforced surfaces (IAM, CMEK, rotation, replication, audit logging).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: docs/development/adding-a-service.md

Goal: the contributor checklist for adding a new service.

**Files:**
- Create: `docs/development/adding-a-service.md`

- [ ] **Step 1: Create `docs/development/adding-a-service.md`**

```markdown
# Adding a new service

This is the canonical checklist for contributors adding a new service to `gcp-local` (Pub/Sub, Firestore, etc.). Follow each step in order; each one references the existing BigQuery / GCS / Secret Manager implementations as templates.

The reason this doc exists: the existing service implementations are the source of truth for "what a service looks like in this repo". This checklist makes sure no piece (especially documentation) gets forgotten.

## 1. Spec

Brainstorm the v1 surface for the service. Decide which APIs are in scope, which are accepted-and-ignored, and which are out of scope.

- Save the spec to `docs/superpowers/specs/YYYY-MM-DD-<service>-design.md`.
- Reference the parent `docs/superpowers/specs/2026-04-24-gcp-local-core-design.md` for cross-cutting conventions.
- Use [`docs/superpowers/specs/2026-04-25-gcp-local-bigquery-design.md`](../superpowers/specs/2026-04-25-gcp-local-bigquery-design.md) as the structural template.

## 2. Plan

Write a TDD plan with bite-sized tasks under `docs/superpowers/plans/YYYY-MM-DD-<service>.md`. Use the BigQuery plan as a template.

The plan should declare a commit policy at the top so subagent-driven execution can commit per task on the feature branch.

## 3. Service package

Create `src/gcp_local/services/<service>/` with the established layout:

| File | Responsibility |
|---|---|
| `service.py` | Implements the `Service` protocol from `gcp_local.core.service`. Owns lifecycle (`start`, `stop`, `reset_state`, `health`). Constructs and tears down the FastAPI app or gRPC server. |
| `app.py` | FastAPI app factory + router wiring (REST services). For gRPC services this is `servicer.py` instead, returning the gRPC servicer. |
| `routes/` (REST) or `handlers.py` (gRPC) | Request handlers. One file per resource group. |
| `engine/` | Anything stateful that's worth its own subpackage (DuckDB connections, schema autodetect, load runners, session stores). |
| `models.py` | Domain dataclasses (records, schemas). |
| `storage.py` | Storage protocol + in-memory and disk-backed implementations. |
| `errors.py` | Service-specific exception types + REST/gRPC error envelope helpers. |
| `names.py` | Resource-name parsers and validators. |

The BigQuery, GCS, and Secret Manager packages are the working templates.

## 4. Register the service via entry point

Add the service to `pyproject.toml`:

```toml
[project.entry-points."gcp_local.services"]
<service> = "gcp_local.services.<service>.service:<Service>Service"
```

The CLI's service-discovery loop (in `gcp_local.core.registry`) instantiates whichever services are listed in the `SERVICES` env var (or all of them by default).

## 5. Tests

- **Unit tests** under `tests/unit/services/<service>/`. One test file per concern (routes, storage, engine, error mapping). Aim for behavior-focused tests, not implementation-detail tests.
- **Integration tests** under `tests/integration/test_<service>_integration.py` driving the real `google-cloud-<service>` Python client against an in-process emulator. The existing `emulator` fixture (in `tests/integration/conftest.py`) is the entry point.

`pytest`, `ruff check .`, `ruff format --check .`, and `mypy src/` must all pass before opening a PR.

## 6. Documentation

This is the bit that gets forgotten. The PR template's documentation checklist enumerates these — repeating them here for clarity:

- [ ] **`docs/services/<service>.md`** — user-facing usage doc. Template: `docs/services/bigquery.md`. Sections: elevator pitch, what's emulated, what's not emulated, connecting (Python client snippet), examples, limits & quirks.
- [ ] **`docs/architecture/<service>.md`** — internals deep-dive. Template: `docs/architecture/bigquery.md`. Sections: at-a-glance, wire & port, storage model, request lifecycle, error mapping, tests, internals-level limitations.
- [ ] **`README.md`** — add a row to the "Services at a glance" table; include both usage and architecture links.
- [ ] **`ROADMAP.md`** — if the service was on the Planned list, move it from Planned → In progress while the work is open, then delete the row when it ships (it now lives in the README table).
- [ ] **`docs/deployment.md`** — add a row to the default-ports table.
- [ ] **`CHANGELOG.md`** — add an entry under `[Unreleased]` describing what landed.

## 7. Pull request

- Open a PR to `master`.
- Fill out the PR template (`.github/pull_request_template.md`), including the documentation checklist above.
- Wait for CI to be green.
- Squash-merge when approved.
- Delete the feature branch (the GitHub PR UI does this with one click).

## 8. Verify the smoke flow

If maestro-evals or another consumer depends on the service, rebuild the gcp-local Docker image and bounce the local rancher-desktop deployment to verify end-to-end:

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
kubectl rollout restart deploy/gcp-local
kubectl rollout status deploy/gcp-local
```

Then run the consumer's smoke test.
```

- [ ] **Step 2: Commit**

```bash
git add docs/development/adding-a-service.md
git commit -m "$(cat <<'EOF'
docs(development): add the new-service contributor checklist

Single canonical source for "how do I add a service to gcp-local"
covering spec → plan → package layout → entry-point registration →
tests → docs (with the doc-update list that the PR template's
checklist mirrors) → PR → smoke verify.

Templates the contributor against the existing BigQuery / GCS /
Secret Manager implementations.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: ROADMAP.md

Goal: roadmap with In-Progress / Planned / Future tiers + per-service follow-ups.

**Files:**
- Create: `ROADMAP.md`

- [ ] **Step 1: Create `ROADMAP.md`**

```markdown
# Roadmap

This document tracks what's actively being built, what's committed to v1, and what's likely post-v1. Implemented services live in the [README](README.md#services-at-a-glance) table; this file is forward-looking.

Status vocabulary:

- **Stable** — feature-complete for v1 scope, no breaking changes expected.
- **Alpha** — implemented and in use, but API surface or internals may shift.
- **Planned** — committed to v1 roadmap, not started yet.
- **Future** — not on the v1 roadmap; would be considered post-v1.

## In progress

| Service | Owner | Started | Tracking |
|---|---|---|---|

(empty — nothing is currently in progress.)

## Planned (v1)

These services are committed to the v1 roadmap. The order is rough; pick whichever you'd like to contribute.

| Service | Wire | Default port | Default env var | Notes |
|---|---|---|---|---|
| Pub/Sub | gRPC | 8085 | `PUBSUB_EMULATOR_HOST` | Topics, subscriptions, push delivery |
| Firestore | gRPC | (TBD) | `FIRESTORE_EMULATOR_HOST` | Documents, queries, indexes |

## Future (post-v1)

These are services we know we'll want eventually but haven't committed to. The list is not exhaustive — anything not listed simply hasn't been considered yet.

| Service | Wire | Default port | Default env var | Notes |
|---|---|---|---|---|
| Cloud Functions | HTTP | (TBD) | (none) | Local function execution |
| Cloud Tasks | gRPC / REST | (TBD) | (none) | Queue + leasing semantics |
| Cloud Spanner | gRPC | (TBD) | `SPANNER_EMULATOR_HOST` | Strong consistency, SQL surface |

## Per-service follow-ups

These are known gaps in the already-implemented (Alpha) services, tracked here so they don't get lost.

### BigQuery

- **GCS-URI load jobs** (`load_table_from_uri('gs://...')`) — deferred from PR #5; needs the cross-service BQ↔GCS wiring sketched in `docs/superpowers/specs/2026-04-26-gcp-local-bigquery-load-jobs-design.md` §11.
- **`maxBadRecords` / `ignoreUnknownValues`** on load jobs — currently accepted but treated as all-or-nothing; correct semantics need partial-row tolerance.
- **CSV cell coercion for DATE / TIMESTAMP / JSON columns** — currently pass-through; relies on DuckDB implicit cast.
- **`statistics.totalBytesProcessed`** — always reports `0`; DuckDB doesn't expose an equivalent metric.
- **Parquet / Avro / ORC source formats** for load jobs.

### GCS

(Pull from `docs/services/gcs.md`'s "What's not emulated" section. Examples likely include: HMAC keys, retention policies, object lock, customer-supplied encryption keys.)

### Secret Manager

- **Real IAM enforcement** — `SetIamPolicy` is accepted and round-tripped but not enforced.
- **CMEK** — accepted, not enforced.
- **Rotation schedules** — not implemented.
- **Audit logging** — not emitted.

## How to update this file

When a Planned service starts being built, move the row to `In progress` and fill `Owner` / `Started` / `Tracking`. When it ships, delete the row entirely — implemented services live in the [README](README.md#services-at-a-glance) table, not here.

When a follow-up gap is closed, delete the bullet from the corresponding `Per-service follow-ups` subsection.

The PR template (`.github/pull_request_template.md`) and the contributor checklist ([`docs/development/adding-a-service.md`](docs/development/adding-a-service.md)) both call out these updates explicitly.
```

- [ ] **Step 2: Commit**

```bash
git add ROADMAP.md
git commit -m "$(cat <<'EOF'
docs: add ROADMAP.md (in-progress / planned / future tiers)

Three-tier roadmap with explicit status vocabulary (Stable / Alpha /
Planned / Future) plus a Per-service follow-ups section that tracks
known gaps in the already-shipped Alpha services.

Implemented services live in the README's services-at-a-glance table,
NOT in this roadmap — when work ships, the row gets deleted from
ROADMAP.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Rewrite README.md

Goal: replace the current short README with the open-source landing page. This task lands last because it links to all the other new docs.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace `README.md` content**

Write the file (using `Write` since it's a full rewrite). The content:

````markdown
# gcp-local

A local emulator for Google Cloud services — the GCP counterpart to LocalStack.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
<!-- TODO: add CI badge once the repo is public and Actions runs against master -->

`gcp-local` lets you point the official `google-cloud-*` Python client libraries at `localhost` and run integration tests, prototypes, and local developer workflows against a real-shaped emulator. No real GCP credentials, no real billing, no flaky network.

## Status

Alpha. Three services are implemented today; two more are planned for v1; see [ROADMAP.md](ROADMAP.md) for what's ahead.

## Services at a glance

| Service | Status | Default port | Wire | Usage | Architecture |
|---|---|---|---|---|---|
| BigQuery | Alpha | 9050 | REST | [usage](docs/services/bigquery.md) | [internals](docs/architecture/bigquery.md) |
| GCS | Alpha | 4443 | REST | [usage](docs/services/gcs.md) | [internals](docs/architecture/gcs.md) |
| Secret Manager | Alpha | 8086 | gRPC | [usage](docs/services/secret-manager.md) | [internals](docs/architecture/secret-manager.md) |
| Pub/Sub | Planned | 8085 | gRPC | — | — |
| Firestore | Planned | (TBD) | gRPC | — | — |

Status vocabulary: **Stable** = feature-complete for v1, **Alpha** = implemented and in use but may shift, **Planned** = committed to v1 but not started, **Future** = post-v1.

## Quickstart

### Run from source

```bash
git clone https://github.com/aGallea/gcp-local.git
cd gcp-local
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m gcp_local
```

Health check:

```bash
curl http://localhost:4510/_emulator/health
```

### Run via Docker

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
docker run --rm -p 4510:4510 -p 4443:4443 -p 8086:8086 -p 9050:9050 gcp-local:dev
curl http://localhost:4510/_emulator/health
```

For docker-compose, Kubernetes, Rancher Desktop, persistence (`PERSIST=1`), and selecting a subset of services with `SERVICES=`, see [`docs/deployment.md`](docs/deployment.md).

## Connect a client

### BigQuery

```python
import os
from google.auth import credentials as ga_credentials
from google.cloud import bigquery
from google.cloud.bigquery import DatasetReference, SchemaField, TableReference

os.environ["BIGQUERY_EMULATOR_HOST"] = "localhost:9050"
client = bigquery.Client(
    project="my-project",
    credentials=ga_credentials.AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:9050"},
)

ds_ref = DatasetReference("my-project", "demo")
client.create_dataset(bigquery.Dataset(ds_ref))

schema = [SchemaField("id", "INT64", mode="REQUIRED"), SchemaField("name", "STRING")]
table_ref = TableReference(ds_ref, "greetings")
client.create_table(bigquery.Table(table_ref, schema=schema))
client.insert_rows_json(table_ref, [{"id": 1, "name": "hello"}])

rows = list(client.query("SELECT * FROM `my-project.demo.greetings`").result())
print(rows)
```

### GCS

```python
import os
from google.auth import credentials as ga_credentials
from google.cloud import storage

os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:4443"
client = storage.Client(
    project="my-project",
    credentials=ga_credentials.AnonymousCredentials(),
)
bucket = client.create_bucket("my-bucket")
bucket.blob("hello.txt").upload_from_string("hi from gcp-local")
print(bucket.blob("hello.txt").download_as_text())
```

### Secret Manager

```python
from google.api_core import client_options as co
from google.auth import credentials as ga_credentials
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient(
    credentials=ga_credentials.AnonymousCredentials(),
    client_options=co.ClientOptions(api_endpoint="localhost:8086"),
    transport="grpc",
)

parent = "projects/my-project"
secret = client.create_secret(
    parent=parent,
    secret_id="my-secret",
    secret={"replication": {"automatic": {}}},
)
client.add_secret_version(parent=secret.name, payload={"data": b"shh"})
print(
    client.access_secret_version(name=f"{secret.name}/versions/latest").payload.data
)
```

## Documentation map

- **Use a service** — [`docs/services/`](docs/services/) (one file per service: BigQuery, GCS, Secret Manager).
- **Run / deploy** — [`docs/deployment.md`](docs/deployment.md).
- **Architecture & internals** — [`docs/architecture/overview.md`](docs/architecture/overview.md) and the per-service files alongside it.
- **Roadmap** — [`ROADMAP.md`](ROADMAP.md).
- **Contribute** — [`CONTRIBUTING.md`](CONTRIBUTING.md). For a brand-new service: [`docs/development/adding-a-service.md`](docs/development/adding-a-service.md).
- **Changelog** — [`CHANGELOG.md`](CHANGELOG.md).

## License

Apache 2.0. See [`LICENSE`](LICENSE).

## Reporting issues

Bugs and feature requests: [GitHub issues](https://github.com/aGallea/gcp-local/issues) (templates available).

Security: see [`SECURITY.md`](SECURITY.md). The TL;DR is: GitHub Security Advisories preferred, `asafgallea@gmail.com` as backup.
````

- [ ] **Step 2: Verify all internal links resolve**

Run a quick link check from the repo root:

```bash
python - <<'EOF'
import re, pathlib, sys
root = pathlib.Path(".")
md_files = [
    "README.md", "ROADMAP.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "SECURITY.md", "CHANGELOG.md",
    "docs/services/secret-manager.md",
    "docs/architecture/overview.md",
    "docs/architecture/bigquery.md",
    "docs/architecture/gcs.md",
    "docs/architecture/secret-manager.md",
    "docs/development/adding-a-service.md",
]
broken = []
link_re = re.compile(r"\]\(([^)]+)\)")
for f in md_files:
    p = root / f
    if not p.exists():
        broken.append(f"missing file: {f}")
        continue
    for m in link_re.findall(p.read_text()):
        if m.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = (p.parent / m.split("#")[0]).resolve()
        if not target.exists():
            broken.append(f"{f}: broken link → {m}")
for b in broken:
    print(b)
sys.exit(1 if broken else 0)
EOF
```

Expected: exit 0, no output. If any broken link, fix the link or fix the target before committing.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: rewrite README as the open-source landing page

Restructured into: 1-paragraph elevator pitch → status → services-at-a-
glance table (with status vocabulary defined inline) → quickstart for
both source and Docker → minimal client connection example per Alpha
service (BigQuery, GCS, Secret Manager) → documentation map →
license/contact pointers.

Anything that needs more space lives in the linked docs:
- ROADMAP.md (planned/future + per-service follow-ups)
- docs/services/<svc>.md (usage)
- docs/architecture/{overview,<svc>}.md (internals)
- docs/deployment.md (Docker, compose, k8s, Rancher Desktop)
- docs/development/adding-a-service.md (contributor checklist)
- CONTRIBUTING.md / CODE_OF_CONDUCT.md / SECURITY.md / CHANGELOG.md

Internal links verified resolved before commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Open the PR

Goal: push the branch and open a PR to `master`.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin oss-readiness-docs
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base master --title "docs: open-source readiness — README, ROADMAP, architecture docs, OSS hygiene files" --body "$(cat <<'EOF'
## Summary

Documentation-only PR that gets the repo ready to publish as a public open-source project.

- Rewritten `README.md` as a landing page with a services-at-a-glance status table.
- New `ROADMAP.md` with In-Progress / Planned / Future tiers + per-service follow-ups.
- New per-service architecture docs under `docs/architecture/` (overview + BigQuery / GCS / Secret Manager).
- New user-facing usage doc for Secret Manager (`docs/services/secret-manager.md`) — was missing.
- New OSS hygiene files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`, `CHANGELOG.md` (Keep-a-Changelog, backfilled with PRs #1–#5).
- New `.github/` issue + PR templates.
- New `docs/development/adding-a-service.md` checklist that the PR template references.

No code changes. Existing usage docs (`docs/services/{bigquery,gcs}.md`) and the deployment guide (`docs/deployment.md`) are untouched.

## Test plan

- [x] `pytest` still green (no code changed)
- [x] `ruff check .` and `ruff format --check .` clean
- [x] `mypy src/` clean
- [x] All internal links in new/rewritten Markdown files resolve (verified by an inline Python checker before the README commit)

## References

- Spec: `docs/superpowers/specs/2026-04-26-open-source-readiness-design.md`
- Plan: `docs/superpowers/plans/2026-04-26-oss-readiness-docs.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Print the PR URL**

`gh pr create` prints the PR URL on success; capture it for the user.

---

## Self-review checklist (run after writing this plan)

- **Spec §1 (overview)** → covered by Tasks 1–11 collectively. ✓
- **Spec §2 (in scope)** — every item maps to a task:
  - README rewrite → Task 11
  - ROADMAP.md → Task 10
  - CONTRIBUTING.md → Task 3
  - CODE_OF_CONDUCT.md → Task 1
  - SECURITY.md → Task 1
  - CHANGELOG.md → Task 2
  - `docs/services/secret-manager.md` → Task 4
  - `docs/architecture/{overview,bigquery,gcs,secret-manager}.md` → Tasks 5, 6, 7, 8
  - `docs/development/adding-a-service.md` → Task 9
  - `.github/` templates → Task 1
  - CHANGELOG backfill of PRs #1–#5 → Task 2 ✓
- **Spec §3 (file layout)** — exactly the layout in this plan's "File structure" section. ✓
- **Spec §4 (README structure)** — Task 11 mirrors §4.1–§4.6. ✓
- **Spec §5 (ROADMAP)** — Task 10 covers §5.1–§5.4. ✓
- **Spec §6 (architecture docs)** — Tasks 5–8 use the section structure from §6.1–§6.4 verbatim. ✓
- **Spec §7 (`docs/services/secret-manager.md`)** — Task 4 covers the seven required sections. ✓
- **Spec §8 (CONTRIBUTING)** — Task 3 covers the seven sections. ✓
- **Spec §9 (`docs/development/adding-a-service.md`)** — Task 9 implements the checklist with the exact 7 doc-update items. ✓
- **Spec §10 (CHANGELOG)** — Task 2 backfills `0.1.0-alpha`. ✓
- **Spec §11 (SECURITY)** — Task 1 covers the three sections. ✓
- **Spec §12 (CODE_OF_CONDUCT)** — Task 1 with the contact email. ✓
- **Spec §13 (.github/ templates)** — Task 1 covers all three templates. ✓
- **Spec §14 (migration order)** — Tasks 1–11 land in the spec's prescribed dependency order. ✓
- **Spec §15 (non-goals)** — explicitly out of scope; no task addresses them. ✓
- **Spec §16 (open items)** — the `0.1.0-alpha` synthetic version is in Task 2; the CI badge `<!-- TODO -->` placeholder is in Task 11 Step 1's README. ✓

**Placeholder scan:** The plan contains TBDs only where the spec explicitly defers them (e.g., Firestore port number, Pub/Sub env var verification at implementation time). These are intentional and called out as such in the relevant tables.

**Type / name consistency:** `<service>` placeholder used consistently; doc paths used consistently; PR template's checklist matches `docs/development/adding-a-service.md`'s §6 list verbatim.

---
