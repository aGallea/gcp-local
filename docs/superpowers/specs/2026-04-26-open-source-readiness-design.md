# gcp-local — Open-Source Readiness Documentation Design

**Date:** 2026-04-26
**Status:** Draft for review
**Scope:** Top-level documentation restructure to make `gcp-local` ready to publish as a public OSS project.

## 1. Overview

`gcp-local` is currently developed as a private project with usage docs (`docs/services/{bigquery,gcs}.md`), a deployment guide (`docs/deployment.md`), and a brief `README.md`. To open the repo to outside contributors and users, the documentation needs:

- A clear landing page that explains what the project is, what's implemented, and how to get started.
- A roadmap that distinguishes "actively being built" / "planned" / "future" so prospective contributors know where to help.
- Per-service architecture docs that explain *how* each service is implemented (separate from the user-facing usage docs).
- Standard OSS hygiene files (`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, GitHub issue/PR templates).
- A documented procedure for adding a new service that lists every doc that needs updating, so the docs don't drift each time a service lands.

This spec describes the file layout, the structure and content of each new/rewritten doc, and the doc-update procedure. It does not prescribe the literal English prose for every paragraph — the implementation plan does that.

## 2. Scope

### In scope

- Rewriting `README.md` as the OSS landing page.
- Adding `ROADMAP.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md` at the repo root.
- Adding `docs/services/secret-manager.md` (the one Stable service that currently has no user-facing usage doc).
- Adding `docs/architecture/{overview,bigquery,gcs,secret-manager}.md`.
- Adding `docs/development/adding-a-service.md`.
- Adding `.github/ISSUE_TEMPLATE/{bug_report,feature_request}.md` and `.github/pull_request_template.md`.
- Backfilling `CHANGELOG.md` with PRs #1–#5 under a `0.1.0-alpha` entry dated 2026-04-26.

### Out of scope

- Changing existing `docs/services/{bigquery,gcs}.md` content (kept as-is — they're already comprehensive usage docs).
- Changing `docs/deployment.md` content (already covers Docker, docker-compose, k8s, rancher-desktop).
- Setting up a docs site generator (mkdocs/sphinx). Plain Markdown rendered by GitHub is enough for v1.
- PyPI publishing setup, GitHub Actions release workflows, signing.
- Any code changes to the services themselves.
- Translations or accessibility-specific tooling.

## 3. File layout

```
README.md                       # rewritten landing page
ROADMAP.md                      # roadmap with three status tiers
LICENSE                         # exists, no change (Apache 2.0)
CONTRIBUTING.md                 # NEW
CODE_OF_CONDUCT.md              # NEW — Contributor Covenant 2.1
SECURITY.md                     # NEW
CHANGELOG.md                    # NEW — Keep-a-Changelog, backfilled

docs/
  deployment.md                 # exists, no change
  services/
    bigquery.md                 # exists, no change — USAGE
    gcs.md                      # exists, no change — USAGE
    secret-manager.md           # NEW — USAGE (was missing)
  architecture/                 # NEW directory
    overview.md                 # cross-cutting design
    bigquery.md
    gcs.md
    secret-manager.md
  development/                  # NEW directory
    adding-a-service.md         # checklist + doc-update steps
  superpowers/                  # exists; specs/plans live here, no change

.github/
  ISSUE_TEMPLATE/
    bug_report.md               # NEW
    feature_request.md          # NEW
  pull_request_template.md      # NEW
```

## 4. README.md (rewritten)

The README is the project's storefront. Structure:

### 4.1 Header

- Title (`# gcp-local`)
- One-paragraph elevator pitch: a local emulator for Google Cloud services, the GCP counterpart to LocalStack, Apache 2.0.
- Status badge line (alpha; Apache 2.0 link). Build/CI badge optional — leave a placeholder comment for when the project goes public.

### 4.2 Services at a glance

A single table:

| Service | Status | Default port | Wire protocol | Usage | Architecture |
|---|---|---|---|---|---|
| BigQuery | Alpha | 9050 | REST | [usage](docs/services/bigquery.md) | [internals](docs/architecture/bigquery.md) |
| GCS | Alpha | 4443 | REST | [usage](docs/services/gcs.md) | [internals](docs/architecture/gcs.md) |
| Secret Manager | Alpha | 8086 | gRPC | [usage](docs/services/secret-manager.md) | [internals](docs/architecture/secret-manager.md) |
| Pub/Sub | Planned | 8085 | gRPC | — | — |
| Firestore | Planned | (TBD) | gRPC | — | — |

Status vocabulary (defined once, used everywhere):
- **Stable** — feature-complete for v1 scope, no breaking changes expected.
- **Alpha** — implemented and in use, but API surface or internals may shift.
- **Planned** — committed to v1 roadmap, not started yet.
- **Future** — not on the v1 roadmap; would be considered post-v1.

### 4.3 Quickstart

Two flavors, both ~5 lines each:

**Run from source:**
```bash
git clone https://github.com/aGallea/gcp-local.git
cd gcp-local
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m gcp_local
```

**Run via Docker:**
```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
docker run --rm -p 4510:4510 -p 4443:4443 -p 8086:8086 -p 9050:9050 gcp-local:dev
curl http://localhost:4510/_emulator/health
```

For docker-compose, Kubernetes, Rancher Desktop, persistence, and service selection, link to `docs/deployment.md`.

### 4.4 Connect a client

One short example per Stable/Alpha service. Each example must be runnable verbatim against a default `gcp-local` instance and produce visible output. Order: BigQuery, GCS, Secret Manager. Each ~10 lines, no superfluous code.

### 4.5 Documentation map

A bulleted list:
- **Use the emulator** — `docs/services/<service>.md` for each service.
- **Run / deploy** — `docs/deployment.md`.
- **Architecture & internals** — `docs/architecture/overview.md` and per-service files.
- **Roadmap** — `ROADMAP.md`.
- **Contribute** — `CONTRIBUTING.md`.
- **Add a service** — `docs/development/adding-a-service.md`.

### 4.6 License & contact

Short closing block: Apache 2.0, link to LICENSE; pointer to CONTRIBUTING.md and SECURITY.md.

## 5. ROADMAP.md

Three sections, each a table. Status vocabulary matches §4.2.

### 5.1 In progress

What's actively being built right now. Often empty (and that's fine — make that explicit). Columns: `Service` / `Owner` / `Started` / `Tracking` (PR or branch link).

### 5.2 Planned (v1)

Services committed to v1 before any 1.0 release. Columns: `Service` / `Wire protocol` / `Default port` / `Default env var` / `Notes`. Initial rows:

| Service | Wire | Port | Env var | Notes |
|---|---|---|---|---|
| Pub/Sub | gRPC | 8085 | `PUBSUB_EMULATOR_HOST` | topics, subscriptions, push delivery |
| Firestore | gRPC | TBD | `FIRESTORE_EMULATOR_HOST` | documents, queries, indexes |

### 5.3 Future (post-v1)

Services we know we'll want eventually but aren't on the v1 commitment. Same columns. Initial rows:

| Service | Wire | Port | Env var | Notes |
|---|---|---|---|---|
| Cloud Functions | HTTP | TBD | (none) | local function execution |
| Cloud Tasks | gRPC/REST | TBD | (none) | TBD |
| Cloud Spanner | gRPC | TBD | `SPANNER_EMULATOR_HOST` | TBD |

(More can be added; the table is the contract — anything not listed is "we haven't thought about it yet".)

### 5.4 Per-service follow-ups

For each Stable/Alpha service, a short subsection listing known gaps with one-liner pointers. Initial content:

- **BigQuery**
  - ~~GCS-URI load jobs (`load_table_from_uri('gs://...')`)~~ — *shipped (PR #8)*.
  - ~~`maxBadRecords` / `ignoreUnknownValues` on load jobs~~ — *shipped (PR #9)*: bad rows tolerated up to the threshold; counts reported in `statistics.load.badRecords`.
  - ~~CSV DATE/TIMESTAMP/DATETIME/TIME/JSON coercion~~ — *shipped*: the CSV path now coerces to typed Python objects. NDJSON for these types still relies on DuckDB's implicit cast.
  - `statistics.totalBytesProcessed` always reports 0 (DuckDB has no equivalent metric).
- **GCS** — populate from gaps already documented in `docs/services/gcs.md`'s "What's not emulated" section.
- **Secret Manager** — populate from the spec at `docs/superpowers/specs/2026-04-24-gcp-local-secret-manager-design.md` once the usage doc is written.

## 6. Architecture docs

### 6.1 docs/architecture/overview.md

Cross-cutting design. Sections:

1. **Service registry** — `Service` protocol (`name`, `default_ports`, `start`, `stop`, `reset_state`, `health`), entry-point discovery (`gcp_local.services` group in `pyproject.toml`), `Context` (per-process state) and `StateHub` (cross-service event bus, currently lightly used).
2. **Admin API** — `/_emulator/health`, `/_emulator/services`, `/_emulator/reset?service=<name>` on port 4510. What each returns.
3. **Lifecycle** — `start()` order, signal handling, `stop()` order, what `reset_state()` does (and doesn't), what `PERSIST=1` changes.
4. **Port overrides** — `<SERVICE>_EMULATOR_PORT` env vars; `port_overrides` field on `Context`; how the CLI assembles the override map.
5. **Common patterns** — error envelopes, AnonymousCredentials posture (no auth enforced), in-memory vs on-disk backends, the vendor-and-commit pattern for proto stubs (`scripts/gen_protos.sh`).
6. **Repository tour** — `src/gcp_local/{core,services,generated}/`, `tests/{unit,integration}/`, `docs/`, `scripts/`. One paragraph each.

### 6.2 docs/architecture/bigquery.md

Service-specific internals. Template (used identically for the other two services):

1. **Wire & port** — REST on 9050; `BIGQUERY_EMULATOR_HOST` honored.
2. **Storage model** — DuckDB single-database file, `_gcp_local_meta` catalog schema, `_gcp_local_jobs` transient schema, project-scoped `<project>:<dataset>` schema naming.
3. **Request lifecycle (representative)** — `client.query("SELECT ...")` traced end-to-end: route → JobRunner → translate (sqlglot AST passes) → DuckDB execute → result materialization → row serialization to BQ wire format.
4. **Translation/shims** — sqlglot dialect=bigquery → DuckDB; AST passes (3-part-name rewrite, wildcard expansion, SAFE.→TRY, INFORMATION_SCHEMA resolution); registered DuckDB UDFs (`GENERATE_UUID`, `FORMAT_DATE`, ...).
5. **Load jobs** — `LoadRunner` overview: parse (NDJSON/CSV) → schema resolution → disposition → batched INSERT. Multipart vs resumable upload split.
6. **What's emulated vs not** — link out to `docs/services/bigquery.md`'s "What's not emulated" section. Internals-level gaps go here: `totalBytesProcessed=0`, single DuckDB connection serialization, time-zone handling.
7. **Tests** — `tests/unit/services/bigquery/` layout, `tests/integration/test_bigquery_integration.py` driving real `google-cloud-bigquery`.
8. **Known internals limitations / TODOs** — same gap list as `ROADMAP.md` §5.4 BigQuery, with file pointers.

### 6.3 docs/architecture/gcs.md

Same template as §6.2. Sections that need different content:

- Storage model — bucket/object layout, in-memory vs disk-backed object stores.
- Request lifecycle — a representative upload (e.g., `client.upload_blob(...)`).
- Translation/shims — none; this is straight REST.

### 6.4 docs/architecture/secret-manager.md

Same template. gRPC-specific notes:

- Storage model — in-process secret/version catalog, no DB engine.
- Wire & port — gRPC on 8086; the `client_options.api_endpoint` pattern (no standard env var).
- Translation/shims — vendored proto stubs in `src/gcp_local/generated/`, regen via `scripts/gen_protos.sh`.

## 7. docs/services/secret-manager.md (USAGE)

Mirrors the structure of `docs/services/{bigquery,gcs}.md`:

1. One-paragraph what-it-emulates.
2. Default port + connection table.
3. **What's emulated** — secrets, versions, IAM permissions surface (or lack thereof), payload size limits.
4. **What's not emulated** — list. Pull from the v1 spec (`docs/superpowers/specs/2026-04-24-gcp-local-secret-manager-design.md`).
5. **Connecting** — Python client snippet using `client_options.api_endpoint`.
6. **Examples** — create secret, add version, access version, list versions, delete.
7. **Limits & quirks** — anything callers should know.

## 8. CONTRIBUTING.md

Sections:

1. **Local dev setup** — clone, venv, `pip install -e ".[dev]"`, run `pytest`, run `ruff check . && ruff format --check . && mypy src/`.
2. **Branch + PR workflow** — branch off `master`, push, open PR, CI must be green before merge, squash-merge convention, delete branch after merge.
3. **Adding a new service** — short blurb pointing to `docs/development/adding-a-service.md`.
4. **Commit message conventions** — `<type>(<scope>): <subject>` matching what's already in the repo (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`). Scope is the service name when the change is scoped to one service.
5. **Code of conduct** — short paragraph + link to `CODE_OF_CONDUCT.md`.
6. **Reporting bugs / requesting features** — pointer to `.github/ISSUE_TEMPLATE/`.
7. **Reporting security issues** — pointer to `SECURITY.md`.

## 9. docs/development/adding-a-service.md

A numbered, copy-pasteable checklist. The audience is a contributor who has never built a `gcp-local` service before.

```
## Adding a new service

### 1. Spec
   - Brainstorm the service surface (which APIs in scope, what's deferred).
   - Save the spec to `docs/superpowers/specs/YYYY-MM-DD-<service>-design.md`.
   - Reference the parent `docs/superpowers/specs/2026-04-24-gcp-local-core-design.md`.

### 2. Plan
   - Write a TDD plan with bite-sized tasks under `docs/superpowers/plans/YYYY-MM-DD-<service>.md`.
   - Use BigQuery's plan as a template.

### 3. Service package
   - Create `src/gcp_local/services/<service>/` with the established layout:
     - `service.py` — implements the `Service` protocol
     - `app.py` — FastAPI/grpc.aio app factory + router wiring
     - `routes/` (REST) or `handlers.py` (gRPC) — request handlers
     - `engine/` — anything stateful
     - `models.py`, `errors.py`, `names.py` — domain types

### 4. Register the service
   - Add an entry to `pyproject.toml` under `[project.entry-points."gcp_local.services"]`.

### 5. Tests
   - Unit tests under `tests/unit/services/<service>/`.
   - Integration tests under `tests/integration/test_<service>_integration.py` driving the real `google-cloud-<service>` client.

### 6. Docs (the bit that gets forgotten)
   - [ ] `docs/services/<service>.md` — usage doc (template: BigQuery's).
   - [ ] `docs/architecture/<service>.md` — internals doc (template: §6.2).
   - [ ] Add a row to `README.md`'s services-at-a-glance table.
   - [ ] Update `ROADMAP.md`: move the service from Planned → In progress → (delete the row when shipped).
   - [ ] Update `docs/deployment.md`'s default-ports table.
   - [ ] Add a `CHANGELOG.md` entry under the `[Unreleased]` section.

### 7. PR
   - Open a PR to `master`, ensure CI is green, squash-merge.
```

The doc-update list (item 6) is exactly the list that the PR template's checklist references.

## 10. CHANGELOG.md (Keep-a-Changelog)

Header reproduces the Keep-a-Changelog 1.1.0 convention.

Initial sections:

```
## [Unreleased]

(empty)

## [0.1.0-alpha] — 2026-04-26

### Added
- BigQuery service: dataset/table CRUD, query (sync + async-shaped), DML, streaming inserts (`tabledata.insertAll`), `INFORMATION_SCHEMA` views, inline NDJSON + CSV load jobs (multipart + resumable). PRs #2, #4, #5.
- GCS service: bucket + object CRUD, multipart and resumable uploads, signed-URL accept-and-ignore.
- Secret Manager service: secret + version CRUD, access by name + version, IAM accept-and-ignore.
- Core framework: service registry, admin API (`/_emulator/health`, `/services`, `/reset`), per-service port overrides, in-memory + disk-backed storage modes (`PERSIST=1`), entry-point service discovery.
- Docker image (`docker/Dockerfile`) and deployment docs covering Docker, docker-compose, Kubernetes (incl. Rancher Desktop). PR #3.

### Known limitations
- Inline-only load jobs (no `gs://` source URIs, no Parquet/Avro/ORC).
- BigQuery `totalBytesProcessed` always reports `0`.
- `maxBadRecords` / `ignoreUnknownValues` on load jobs accepted but treated as all-or-nothing.
```

Future PRs add an `Added` / `Changed` / `Fixed` / `Deprecated` / `Removed` line under `[Unreleased]`.

## 11. SECURITY.md

Short. Three sections:

1. **Scope** — `gcp-local` is a local-development emulator. It accepts unauthenticated requests by design and stores no real secrets or production data. The threat model is "developer's local machine".
2. **Reporting a vulnerability** — preferred channel is GitHub Security Advisories on the `aGallea/gcp-local` repository. Backup channel: email `asafgallea@gmail.com`. We acknowledge within 7 days.
3. **Out of scope** — DoS against an emulator running on a developer's laptop, weak randomness in fake IDs, lack of TLS on local ports, accepting any credentials.

## 12. CODE_OF_CONDUCT.md

Verbatim Contributor Covenant 2.1, with the contact line set to `asafgallea@gmail.com`.

## 13. .github/ templates

### 13.1 ISSUE_TEMPLATE/bug_report.md

Markdown frontmatter for GitHub. Fields:
- Service affected (BigQuery / GCS / Secret Manager / core / other)
- gcp-local version or commit SHA
- Reproduction steps (numbered list)
- Expected behavior
- Actual behavior
- Logs / output

### 13.2 ISSUE_TEMPLATE/feature_request.md

- Service affected
- What real GCP behavior should be emulated (with link to GCP docs)
- Why it matters / use case
- Proposed approach (optional)

### 13.3 pull_request_template.md

```
## Summary

<one to three bullets describing what this PR does and why>

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

<links to spec, plan, related issues>
```

## 14. Migration & order of operations

The implementation plan should land these in dependency order:

1. New OSS hygiene files (`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, `.github/`) — no dependencies.
2. `docs/services/secret-manager.md` (USAGE) — no dependencies.
3. `docs/architecture/overview.md` plus the three service files — content references `docs/services/*` (already exists) and the new Secret Manager usage doc.
4. `docs/development/adding-a-service.md` — references all of the above.
5. `ROADMAP.md` — references all of the above.
6. `README.md` rewrite — references everything; lands last so its doc-map links resolve.

The plan can land these in 1-2 commits if the diffs stay reviewable, or break each numbered group into its own commit. Either is fine; the plan will pick.

## 15. Non-goals recap

This spec does not describe: docs site generator setup, CI badge wiring, PyPI publishing, GitHub release automation, project governance docs (`GOVERNANCE.md`, `MAINTAINERS.md`), translation infrastructure, accessibility tooling, or any code changes to services.

## 16. Open items

- The `0.1.0-alpha` version label in `CHANGELOG.md` is a synthetic anchor for backfill; no git tag is created at this stage. A real `v0.1.0-alpha` tag can be cut after this doc work merges, but that's an explicit follow-up.
- README's CI/build badge URLs are left as a `<!-- TODO: add when public -->` comment until the repo is made public and Actions runs against `master`.
- Pub/Sub and Firestore default ports/env vars in `ROADMAP.md` are documented from intent; confirm at implementation time.
