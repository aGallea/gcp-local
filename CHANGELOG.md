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
