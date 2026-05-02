# Changelog

All notable changes to `gcp-local` are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once a 1.0 release is cut.

Releases are managed by [release-please](https://github.com/googleapis/release-please) — it scans Conventional Commits on `master` and opens a Release PR that bumps `pyproject.toml`, promotes `[Unreleased]` to a versioned section, and tags `vX.Y.Z` on merge. You don't need to edit this file by hand for normal commits; release-please derives entries from commit subjects.

## [0.2.1](https://github.com/aGallea/gcp-local/compare/v0.2.0...v0.2.1) (2026-05-02)


### Fixed

* **ci:** release-please uses RELEASE_TOKEN PAT so tag pushes trigger publish-image ([2ee35fb](https://github.com/aGallea/gcp-local/commit/2ee35fb565bc3a73c27d892cef98987b6904a472))
* **ci:** release-please uses RELEASE_TOKEN so tag pushes trigger publish-image ([b37e89b](https://github.com/aGallea/gcp-local/commit/b37e89b2440b808acd131444ef010dced2063f1b))

## [0.2.0](https://github.com/aGallea/gcp-local/compare/v0.1.0...v0.2.0) (2026-05-02)


### Added

* **examples:** add main.py narrated demo ([a36e9ce](https://github.com/aGallea/gcp-local/commit/a36e9ce42a910c67d62c9fb1946e5fab1cabfd20))
* **examples:** add order-pipeline e2e example + CI workflow ([6b24239](https://github.com/aGallea/gcp-local/commit/6b24239d2105dc2e1f0cda3b632d6e64edb1596f))
* **examples:** OrderPipeline.__init__ with wait-for-ready ([5e75a63](https://github.com/aGallea/gcp-local/commit/5e75a63bbbe6eb1c408c7d8eebc97bb6daf51c87))
* **examples:** place_order + confirm_pending_orders + daily_totals ([8cc1c4d](https://github.com/aGallea/gcp-local/commit/8cc1c4dfb75a47aa43832f00ed13f1ed8611ab9a))
* **examples:** scaffold order-pipeline directory with docker-compose ([b088840](https://github.com/aGallea/gcp-local/commit/b08884020ecee50173c11878222fd08ee49d8dc2))
* **examples:** seed payment-api-key via Secret Manager ([9205fff](https://github.com/aGallea/gcp-local/commit/9205fff069800124eb0d8f4466a21d449929d9f4))
* **examples:** wire BigQuery dataset + insert/select helpers ([b1085af](https://github.com/aGallea/gcp-local/commit/b1085afd3caa625017fa9d8fd6b3f43f701c8574))
* **examples:** wire Firestore client + order-doc helpers ([12b3fee](https://github.com/aGallea/gcp-local/commit/12b3fee67e1c716ed940628901c49fa0158b65ee))
* **examples:** wire GCS bucket + invoice upload helpers ([dd8225d](https://github.com/aGallea/gcp-local/commit/dd8225d56b43b2ddbfbb91a38f4b64b63185e0dc))
* **examples:** wire Pub/Sub topic + publish/pull helpers ([dae4e09](https://github.com/aGallea/gcp-local/commit/dae4e09e3dc9159a821cd913d49cd5b92ffcfc90))

## [Unreleased]

## [0.1.0] — 2026-05-01

The first managed release. Captures everything that landed up to and including the Firestore service (PR #14) and the GHCR container-image publishing pipeline (PR #15). Future releases are managed by release-please from Conventional Commits going forward.

### Fixed

- **GCS:** populate `kind`, `id`, `selfLink`, `mediaLink`, and `storageClass` on every object/bucket JSON response. `gcloud storage cat`/`cp` previously crashed with a `TypeError: endswith first arg must be bytes` because its apitools download path threads `metadata.mediaLink` through `urllib.parse.urlsplit`, which coerces `None` into bytes when the field is absent.
- **GCS:** accept apitools' single-quoted multipart `boundary` parameter (`boundary='===abc==='`). Python's `email` parser only honors unquoted or double-quoted boundaries per RFC 2045/2046; we now normalize before parsing. `gcloud storage cp` previously failed with "multipart parse error: list index out of range".
- **BigQuery:** TIMESTAMP query results now serialize as integer microseconds since epoch (was float-seconds). Matches what `google-cloud-bigquery`'s `CellDataParser` expects (it parses with `int(value)`); the previous `1705322096.000000` form raised `ValueError` in the client.

### Added

- **Firestore (Native mode) service (port 8080, gRPC)** — fifth and final v1 service. Implements CRUD (GetDocument / BatchGetDocuments / ListDocuments / ListCollectionIds / CreateDocument / UpdateDocument / DeleteDocument), atomic Commit + BatchWrite with preconditions and per-write status, structured queries (filters including composite AND/OR, orderBy, cursors, offset, limit, collection-group), aggregations (count with `up_to`, sum, avg), field transforms (SERVER_TIMESTAMP, Increment, arrayUnion, arrayRemove, max/min), optimistic-concurrency transactions with TTL sweeping (60 s), multi-database namespacing, FirestoreAdmin index accept-and-ignore (CreateIndex / GetIndex / ListIndexes / DeleteIndex), and JSON-on-disk persistence under `PERSIST=1` (one file per `(project, database)`). `Listen`, security rules, exports/imports, PartitionQuery, and composite-index enforcement deferred — see ROADMAP.
- **Container images on GitHub Container Registry.** `ghcr.io/agallea/gcp-local:latest` is published from every push to `master`; `master-<short-sha>` for traceability; semver tags (`vX.Y.Z`, `vX.Y`) when a `v*` tag is pushed. Multi-arch (`linux/amd64`, `linux/arm64`). Build cached via GitHub Actions cache to keep CI fast. The publish job runs only after the local Docker smoke test passes, so untested images never reach the registry.
- **Pub/Sub service (port 8085, gRPC)** — fourth v1 service. Implements Publisher (CreateTopic / GetTopic / UpdateTopic / DeleteTopic / ListTopics / ListTopicSubscriptions / Publish) and Subscriber (CreateSubscription / GetSubscription / UpdateSubscription / DeleteSubscription / ListSubscriptions / Pull / Acknowledge / ModifyAckDeadline / StreamingPull / Seek-by-time) over the official `google-cloud-pubsub` wire. At-least-once delivery with ack-deadline-based redelivery (1s sweep), ordering keys with per-key serialization across NACK→redelivery, and seek-to-time. Storage is in-memory only; `PERSIST=1` is ignored. Push subscriptions, filters, schemas, snapshots, and exactly-once delivery are accepted-and-ignored or deferred — see `docs/services/pubsub.md` and `ROADMAP.md`.
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

[Unreleased]: https://github.com/aGallea/gcp-local/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aGallea/gcp-local/releases/tag/v0.1.0
[0.1.0-alpha]: https://github.com/aGallea/gcp-local/releases/tag/v0.1.0-alpha
