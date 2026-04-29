# Changelog

All notable changes to `gcp-local` are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once a 1.0 release is cut.

Add new entries under `[Unreleased]` as part of every PR that changes user-visible behavior. Promote `[Unreleased]` to a versioned section when cutting a release.

## [Unreleased]

### Fixed

- **GCS:** populate `kind`, `id`, `selfLink`, `mediaLink`, and `storageClass` on every object/bucket JSON response. `gcloud storage cat`/`cp` previously crashed with a `TypeError: endswith first arg must be bytes` because its apitools download path threads `metadata.mediaLink` through `urllib.parse.urlsplit`, which coerces `None` into bytes when the field is absent.
- **GCS:** accept apitools' single-quoted multipart `boundary` parameter (`boundary='===abc==='`). Python's `email` parser only honors unquoted or double-quoted boundaries per RFC 2045/2046; we now normalize before parsing. `gcloud storage cp` previously failed with "multipart parse error: list index out of range".
- **BigQuery:** TIMESTAMP query results now serialize as integer microseconds since epoch (was float-seconds). Matches what `google-cloud-bigquery`'s `CellDataParser` expects (it parses with `int(value)`); the previous `1705322096.000000` form raised `ValueError` in the client.

### Added

- **BigQuery:** NDJSON load jobs now coerce string `DATE` / `TIME` / `DATETIME` / `TIMESTAMP` cells to typed Python objects before insert, mirroring the CSV coercion shipped previously. Malformed values raise BQ-shaped errors and bucket under `maxBadRecords` instead of falling through to DuckDB's implicit cast. Non-string values for those columns still pass through unchanged so Unix-timestamp numbers continue to work.
- **BigQuery:** CSV load jobs now coerce `DATE`, `TIME`, `DATETIME`, `TIMESTAMP`, and `JSON` cells to typed Python objects before insert. Malformed values raise BQ-shaped errors and bucket under `maxBadRecords` instead of propagating DuckDB cast failures. Boolean coercion also broadens to accept `t`/`T`/`1`/`yes`/`y` (and the falsey equivalents) per real BQ semantics.
- **BigQuery:** `maxBadRecords` and `ignoreUnknownValues` are now honored on load jobs. Previously they were accepted but the load aborted on the first bad row. Now bad rows (REQUIRED-field violations, unknown fields when the flag is off, CSV column-count mismatches) are tolerated up to `maxBadRecords` (default `0`); the count surfaces in `statistics.load.badRecords`. `ignoreUnknownValues` strips schema-unknown keys from NDJSON rows and drops trailing extra columns from wide CSV rows.
- **BigQuery:** GCS-URI load jobs — `client.load_table_from_uri("gs://bucket/path", ...)` now works for NDJSON and CSV, including glob patterns (`gs://b/dir/*.ndjson`, `gs://b/data/**`) and multi-URI lists. The BigQuery service resolves `gs://` URIs over HTTP against a configurable endpoint: `BIGQUERY_GCS_URI_ENDPOINT` → `STORAGE_EMULATOR_HOST` → loopback to the in-process gcp-local GCS service.
- **GCS:** `GET /storage/v1/b/<bucket>/storageLayout` endpoint returning `kind=storage#storageLayout` so gcloud's preflight call no longer 404s.

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

- BigQuery load jobs do not yet support binary source formats (Parquet / Avro / ORC). NDJSON and CSV are supported for both inline payloads and `gs://` source URIs.
- BigQuery `statistics.totalBytesProcessed` always reports `0` — DuckDB does not expose an equivalent metric.
- Authentication is not enforced on any service; clients must use `AnonymousCredentials`.

[Unreleased]: https://github.com/aGallea/gcp-local/compare/main...HEAD
[0.1.0-alpha]: https://github.com/aGallea/gcp-local/releases/tag/v0.1.0-alpha
