# Changelog

All notable changes to `gcp-local` are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once a 1.0 release is cut.

Releases are managed by [release-please](https://github.com/googleapis/release-please) — it scans Conventional Commits on `master` and opens a Release PR that bumps `pyproject.toml`, promotes `[Unreleased]` to a versioned section, and tags `vX.Y.Z` on merge. You don't need to edit this file by hand for normal commits; release-please derives entries from commit subjects.

## [0.5.1](https://github.com/aGallea/gcp-local/compare/v0.5.0...v0.5.1) (2026-05-09)


### Fixed

* make python -m gcp_local work on the host ([33337e9](https://github.com/aGallea/gcp-local/commit/33337e904015375c1245dae93faa3ace2417ac74))
* make python -m gcp_local work on the host ([720d043](https://github.com/aGallea/gcp-local/commit/720d043d83c57ebba62942bf01ade58ee3f95147))

## [0.5.0](https://github.com/aGallea/gcp-local/compare/v0.4.0...v0.5.0) (2026-05-09)


### Added

* **ui:** add BigQuery browser UI ([fa1c1d1](https://github.com/aGallea/gcp-local/commit/fa1c1d1cf34c46d565e82c68be2958b4dbb56ab4))
* **ui:** add BigQuery browser UI ([bbd9bfe](https://github.com/aGallea/gcp-local/commit/bbd9bfe0d74e22279b4377aba3a9bc306e0cb0f9))
* **ui:** add gcp-local logo, favicon, and README hero ([bb1ebc3](https://github.com/aGallea/gcp-local/commit/bb1ebc311a39006f436beebdf593ccdd871b946b))

## [Unreleased]

### Added

- **BigQuery browser UI**: project / dataset / table navigation, schema view with paged row preview, and an ad-hoc SQL query console. Served at `http://localhost:4510/ui/bigquery`, backed by a new `/_emulator/ui-api/v1/bigquery/...` namespace that reads and writes the same `BigQueryStorage` and `JobRunner` instances as the wire surface on port 9050.
- **`python -m gcp_local`**: added `src/gcp_local/__main__.py` so the package can be invoked as a module, alongside the existing `gcp-local` console script.
- **`.python-version`**: pinned to `3.13` for `pyenv` / `uv` users; matches `requires-python` in `pyproject.toml`.

### Changed

- **Default `data_dir` on the host**: `cli.entrypoint()` now defaults to `./.gcp-local-data` (cwd-relative) instead of `/data`, which was unwritable when running outside Docker. The Docker image keeps the previous behavior by setting `GCP_LOCAL_DATA_DIR=/data` in the Dockerfile env.

## [0.4.0](https://github.com/aGallea/gcp-local/compare/v0.3.0...v0.4.0) (2026-05-04)


### Added

* **gcs:** expose GcsService.storage publicly for ui-api ([8684346](https://github.com/aGallea/gcp-local/commit/8684346bc00d90068062ce1684655ba5832ec683))
* services UI foundation + GCS pilot ([01fc044](https://github.com/aGallea/gcp-local/commit/01fc044d14d83aebf2daade31362ef5097881e94))
* **ui-api:** add error envelope and exception handlers ([6c708b7](https://github.com/aGallea/gcp-local/commit/6c708b7ed7b74f97079bd316f2df4d7606d1448d))
* **ui-api:** add router with /services endpoint ([a773cb2](https://github.com/aGallea/gcp-local/commit/a773cb2fa28a6657f845ce167d47846ea1fe2651))
* **ui-api:** blob metadata with text/json/image previews ([8923c90](https://github.com/aGallea/gcp-local/commit/8923c9071e02c6814afbde761d8ced64b58f5ec8))
* **ui-api:** DELETE /gcs/buckets/{b}/blobs/{n} removes a blob ([b2d1fa6](https://github.com/aGallea/gcp-local/commit/b2d1fa6c0bc24fe09f7a710dd13648b98587942b))
* **ui-api:** DELETE /gcs/buckets/{bucket} with force flag ([4c8c387](https://github.com/aGallea/gcp-local/commit/4c8c387a02214e3db30efdf8191ec78183138730))
* **ui-api:** GET /gcs/buckets lists buckets ([6a461b6](https://github.com/aGallea/gcp-local/commit/6a461b680d0eefdd69edabc84b6ec1e39fdc1512))
* **ui-api:** GET /gcs/buckets/{b}/blobs/{n}/download returns bytes ([3330a69](https://github.com/aGallea/gcp-local/commit/3330a69765d942f4acaadac72ce66ab03e6a6229))
* **ui-api:** list blobs with prefix/delimiter/page support ([828a211](https://github.com/aGallea/gcp-local/commit/828a21102755afb295d1470ad7bdbe8306e106af))
* **ui-api:** mount ui-api router on admin app ([944b2dc](https://github.com/aGallea/gcp-local/commit/944b2dc5e0ca26978d0d0ecabf2dc88d8ac28430))
* **ui-api:** POST /gcs/buckets creates a bucket ([e59e3ab](https://github.com/aGallea/gcp-local/commit/e59e3abfe410f6800d293c159e36ab14342c7c91))
* **ui-api:** scaffold gcs router with schemas and storage dep ([e2104c1](https://github.com/aGallea/gcp-local/commit/e2104c18c3a6978d80d28170bf5eadad21827013))
* **ui-api:** upload blob with multipart and size cap ([3472eeb](https://github.com/aGallea/gcp-local/commit/3472eeb0f0665af7e455e29b5b051c57aabd68b9))
* **ui:** mount /ui/ static bundle with friendly fallback ([427fcb5](https://github.com/aGallea/gcp-local/commit/427fcb5f0885374df7a4788b2a3eca6b884651a6))
* **web:** AppLayout shell with sidebar nav and disabled services ([fe69915](https://github.com/aGallea/gcp-local/commit/fe699158d1d7394ec4ad13ab5d8944ab188243d8))
* **web:** blob list with prefix navigation and delete-with-confirm ([7727efc](https://github.com/aGallea/gcp-local/commit/7727efc0dcbea1aaa72958391e9727dcda5c3401))
* **web:** blob preview with text/json/image and download ([24d81af](https://github.com/aGallea/gcp-local/commit/24d81af2c342da3bd2e8a0429614ad15db15d465))
* **web:** blob upload with drag-drop and file picker ([d85b54e](https://github.com/aGallea/gcp-local/commit/d85b54e35513f7bb12ac115164f62a7971b2d9f7))
* **web:** clickable breadcrumb segments ([752204c](https://github.com/aGallea/gcp-local/commit/752204c4173c14c41dade49deec90315c5ba1ac2))
* **web:** create folder via empty placeholder object ([09a3074](https://github.com/aGallea/gcp-local/commit/09a307417bf7cd0ae59a1b41e6b074182acf2a2b))
* **web:** delete folder placeholder via confirm dialog ([b792aa0](https://github.com/aGallea/gcp-local/commit/b792aa0a5a8a1fef4d58c83aab86abe249fba5d8))
* **web:** EmptyState, ErrorBanner, ConfirmDialog primitives ([c3ce193](https://github.com/aGallea/gcp-local/commit/c3ce193485c3221b3b1decaa291c86282b7d5f70))
* **web:** GCS bucket list with create + delete-with-confirm ([3287e85](https://github.com/aGallea/gcp-local/commit/3287e8537afec8675ede50e2108d962df254a33f))
* **web:** scaffold React + Vite + TS + vitest ([e9487cc](https://github.com/aGallea/gcp-local/commit/e9487ccc74be81599252815412a96c9d675275b0))
* **web:** typed UiApi client with envelope error handling ([2ee5a73](https://github.com/aGallea/gcp-local/commit/2ee5a733a23b6f5f4621792955cc87f8bf9d7b2f))
* **web:** useAsync hook and wire services list into App ([9a49d83](https://github.com/aGallea/gcp-local/commit/9a49d831b545a7a83b136191ac34727cd401bbc1))


### Fixed

* **gcs:** collision check ignores orphan files and trailing-slash names ([8c92229](https://github.com/aGallea/gcp-local/commit/8c92229578445450485beef9020bf8a6cbbc8333))
* **gcs:** DiskStorage handles object names ending in '/' ([3a70207](https://github.com/aGallea/gcp-local/commit/3a7020770bb4f0f63158db23d68cb3393179b4a4))
* **gcs:** DiskStorage list_objects skips orphan bytes-only files ([c5b0cbb](https://github.com/aGallea/gcp-local/commit/c5b0cbb1799cb952390d407e69436c0e5091a01a))
* **ui:** SPA history-mode fallback for deep links ([ce6426d](https://github.com/aGallea/gcp-local/commit/ce6426dd63e1628b100b116509b7c99ae25ca2f1))

## [0.3.0](https://github.com/aGallea/gcp-local/compare/v0.2.1...v0.3.0) (2026-05-03)


### Added

* **pubsub:** deliver push subscriptions via HTTP POST ([2b47783](https://github.com/aGallea/gcp-local/commit/2b47783ef1035c8d0e8aca42c1defac2247df2ee))
* **pubsub:** deliver push subscriptions via HTTP POST ([54ad644](https://github.com/aGallea/gcp-local/commit/54ad644bd574d515cf00946ee68bdbad078b0406))


### Fixed

* **gcs:** wire-serialize int64/uint64 fields as JSON strings ([9b43613](https://github.com/aGallea/gcp-local/commit/9b43613a457a4a7f2ed04efe6112e53d3c02de01))
* **gcs:** wire-serialize int64/uint64 fields as JSON strings ([d4711aa](https://github.com/aGallea/gcp-local/commit/d4711aa8b24eda76d29a7a262d84d1374812aebc))

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

### Added

- **Pub/Sub:** push subscriptions now deliver. When `Subscription.pushConfig.pushEndpoint` is set, the emulator POSTs each published message to the endpoint as a wrapped JSON envelope (`{message: {data, attributes, messageId, publishTime, orderingKey}, subscription}`). 2xx acks the message; anything else (non-2xx, connection error, 30 s timeout) NACKs and the existing ack-deadline redelivery sweeper redrives. `UpdateSubscription` with the `push_config` mask hot-swaps the pump endpoint or flips push↔pull. `oidcToken`, `retryPolicy` backoff, `pushConfig.attributes`, and `noWrapper` remain deferred — see [`docs/services/pubsub.md`](docs/services/pubsub.md).

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
