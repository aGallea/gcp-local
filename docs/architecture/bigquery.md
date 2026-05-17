# BigQuery — internals

This document describes how the BigQuery emulator is implemented. For the user-facing API surface (what's emulated, how to connect, examples), see [`docs/services/bigquery.md`](../services/bigquery.md). For the cross-cutting framework that this service plugs into, see [`docs/architecture/overview.md`](overview.md).

## At a glance

The BigQuery emulator is a FastAPI app that serves the BigQuery REST API on port 9050. SQL execution is delegated to an embedded [DuckDB](https://duckdb.org/) connection; incoming BigQuery SQL is parsed and translated to DuckDB SQL via [sqlglot](https://github.com/tobymao/sqlglot) before execution. Catalog metadata (dataset records, table records with BigQuery-flavored field modes and partitioning info) lives in dedicated `_gcp_local_meta` tables inside the same DuckDB database. Query results materialize into transient temp tables under `_gcp_local_jobs` for paging.

The emulator is **not** a real BigQuery: there is one execution lane (a single DuckDB connection serialized via a thread executor), no real cost or quota model, and `statistics.totalBytesProcessed` is always `0`. Workflows that drive the official `google-cloud-bigquery` Python client work end-to-end; workflows that depend on real Dremel-shaped query semantics will not.

## Wire & port

REST on port `9050`. The official Python client honors `BIGQUERY_EMULATOR_HOST=localhost:9050` and routes there with an insecure HTTP channel. Older client-library versions that don't honor the env var cleanly can use `client_options={"api_endpoint": "http://localhost:9050"}` instead. The cross-service admin API (`/_emulator/health`, etc.) lives on port `4510`, not on 9050.

The service registers as `bigquery` (the entry-point in `pyproject.toml`'s `[project.entry-points."gcp_local.services"]` block). It can be selected via `SERVICES=bigquery` (or as part of a comma-separated list).

## Storage model

A single DuckDB database file holds everything across all projects. The schema layout:

| Logical resource | DuckDB schema | DuckDB table |
|---|---|---|
| `<project>.<dataset>.<table>` | `"<project>:<dataset>"` (always quoted) | `"<table>"` (always quoted) |
| Job-result temp tables | `"_gcp_local_jobs"` | `"_job_<job_id>"` |
| Service catalog rows | `"_gcp_local_meta"` | `datasets`, `tables` |

The `:` separator in schema names is unambiguous because BigQuery project IDs forbid `:` and dataset IDs forbid every character outside `[A-Za-z0-9_]`. DuckDB accepts `:` inside double-quoted identifiers, and we always quote schema names in emitted SQL. The form intentionally mirrors BigQuery's own legacy `project:dataset.table` notation.

By default the connection is `duckdb.connect(":memory:")` — state evaporates when the process exits. Setting `PERSIST=1` switches to `/data/bigquery.duckdb` on the container's `/data` volume; datasets, tables, and row data persist across restarts. Job records and result temp tables are intentionally not persisted (see [Job records and TTL](#job-records-and-ttl)).

## Catalog vs DuckDB

Why an explicit catalog on top of DuckDB's own `information_schema`? BigQuery has metadata DuckDB doesn't model:

- Field modes (`REQUIRED` / `NULLABLE` / `REPEATED`) — DuckDB columns only know nullability.
- Field descriptions and labels.
- Partitioning configuration (`time_partitioning`, `range_partitioning`) — accepted at table-create time and stored verbatim, even though we don't enforce partitioning at query time.
- Clustering configuration — same: stored, not enforced.
- RFC3339 creation/modification timestamps.

`_gcp_local_meta.datasets` and `_gcp_local_meta.tables` each store one row per resource as a single `record JSON` column (the dataclass round-trip), keyed by `(project, dataset_id[, table_id])`. The DuckDB schemas/tables are materialized alongside catalog rows: when `BigQueryStorage.create_table()` runs, it writes the catalog row *and* runs `CREATE TABLE "p:d"."t" (...)` so the data side and the metadata side stay in lockstep. Drops cascade through `DROP SCHEMA ... CASCADE` plus `DELETE FROM` on the catalog.

The catalog is the source of truth for fields DuckDB doesn't preserve — when serializing query results back to BigQuery wire format, we look up the BigQuery type from the catalog rather than from `information_schema.columns`.

## Type mapping

| BigQuery type | DuckDB type | Notes |
|---|---|---|
| `STRING` | `VARCHAR` | |
| `BYTES` | `BLOB` | |
| `INT64` / `INTEGER` | `BIGINT` | |
| `FLOAT64` / `FLOAT` | `DOUBLE` | |
| `BOOL` / `BOOLEAN` | `BOOLEAN` | |
| `NUMERIC` | `DECIMAL(38, 9)` | |
| `BIGNUMERIC` | `DECIMAL(38, 18)` | Documented narrower precision than real BQ (38, 38) |
| `DATE` | `DATE` | |
| `TIME` | `TIME` | |
| `TIMESTAMP` | `TIMESTAMP WITH TIME ZONE` | UTC-stored, UTC-returned |
| `DATETIME` | `TIMESTAMP` | DuckDB conflates with TIMESTAMP; see below |
| `JSON` | `JSON` | |
| `RECORD` / `STRUCT` | `STRUCT(...)` | Nested |
| `ARRAY<T>` (mode `REPEATED`) | `T[]` (LIST) | |
| `GEOGRAPHY` | (rejected at create) | `INVALID_ARGUMENT` |
| `INTERVAL`, `RANGE` | (rejected) | `INVALID_ARGUMENT` |

**`TIMESTAMP` vs `DATETIME` round-trip.** DuckDB stores both as the same physical type, so `information_schema.columns` can't distinguish them. The catalog (which retains the BigQuery-declared type) is the source of truth at row-serialization time — clients see `TIMESTAMP` in their responses for `TIMESTAMP` columns and `DATETIME` for `DATETIME` columns, regardless of what DuckDB's schema tooling reports.

## Request lifecycle: SELECT query

Trace `client.query("SELECT * FROM `p.d.t` WHERE x > 10")` end-to-end:

1. **Route** — `routes/jobs.py::query_sync` (or `insert_job` for `jobs.insert`) handles the POST. Path validation happens first: `validate_project_id`, `validate_job_id`.
2. **JobRunner** — control passes to `JobRunner.run_query(project, job_id, sql)` (in `engine/jobs.py`).
3. **Translate** — `engine/translate.py::translate(sql, catalog)` parses with `sqlglot.parse_one(sql, read="bigquery")`, runs the AST passes (see [SQL translation](#sql-translation)), then emits with `tree.sql(dialect="duckdb")`.
4. **Execute** — `BigQueryConnection.execute(translated)` runs the SQL inside a single-worker `ThreadPoolExecutor`. Every DuckDB call goes through this executor so the underlying `duckdb.DuckDBPyConnection` is touched from one OS thread.
5. **Materialize (SELECT path)** — for SELECTs, the runner emits `CREATE TABLE "_gcp_local_jobs"."_job_<job_id>" AS <translated>`, then `SELECT count(*) FROM ...` to capture `total_rows`, then `DESCRIBE` to recover the result-column types. The result schema is stored on `JobRunner._job_schemas[job_id]`.
6. **Build JobRecord** — `state="DONE"`, `statement_type="SELECT"`, `destination_table=("_gcp_local", "_gcp_local_jobs", "_job_<job_id>")`, `total_rows=N`, `total_bytes_processed=0`. The runner stashes the record in its `_jobs` dict keyed by `(project, job_id)`.
7. **Serialize** — `routes/jobs.py::job_to_api` emits the `Job` resource. For paged responses (`getQueryResults`, `query_sync` first page), `JobRunner.read_page(job_id, page_size, page_token)` runs `SELECT * FROM "_gcp_local_jobs"."_job_<job_id>" LIMIT ? OFFSET ?`, then maps DuckDB rows to BigQuery `f`/`v` wire format using the catalog-derived schema (via `types.duckdb_value_to_bq_wire`). A `maxResults=0` request is special-cased: per the BigQuery convention used by python-bigquery's `QueryJob.result()` poll loop, the response carries `schema` + `totalRows` but **no** `rows` and **no** `pageToken` — the client uses absence of `rows` to detect that the empty page is not a real first page and re-fetches from offset 0.

DML statements (INSERT / UPDATE / DELETE / MERGE) skip step 5 — they execute directly and report `numDmlAffectedRows` / `dmlStats` based on DuckDB's affected-row counts.

## SQL translation

`engine/translate.py::translate(sql, catalog) -> str` runs a fixed pipeline:

1. **Reject legacy SQL** — `#legacySQL` directive at the start of the query → `UnsupportedSql`.
2. **Reject banned features** — regex pre-pass catches `ML.*`, `ST_*`, scripting (`DECLARE`, `BEGIN`, `EXCEPTION`), `FOR SYSTEM_TIME AS OF` time-travel.
3. **Parse** — `sqlglot.parse_one(sql, read="bigquery")` → AST.
4. **Rewrite `INFORMATION_SCHEMA`** — references like `` `p.d.INFORMATION_SCHEMA.TABLES` `` are replaced with subqueries over `_gcp_local_meta` (see [INFORMATION_SCHEMA](#information_schema)).
5. **Expand wildcard tables** — `` `p.d.events_*` `` becomes a `UNION ALL` of every `events_*` table the catalog knows about. The runner pre-fetches candidate IDs only when the query text contains a wildcard pattern (`*\``, `*'`, or `_*`); otherwise the catalog isn't consulted at all.
6. **Rewrite three-part names** — `` `project.dataset.table` `` becomes the schema-qualified `"project:dataset"."table"`.
7. **Rewrite `SAFE.<fn>`** — `SAFE.<fn>(args)` becomes `TRY(<fn>(args))`. Two cases: `sqlglot.exp.SafeFunc` (for known functions) and `sqlglot.exp.Anonymous` with a `SAFE.` prefix (for unknown functions).
8. **Strip partitioning DDL on `CREATE TABLE`** — `PARTITION BY` and `CLUSTER BY` clauses are removed from the AST so DuckDB accepts the DDL. The catalog still stores the partitioning intent — it's just not enforced at query time.
9. **Emit DuckDB SQL** — `tree.sql(dialect="duckdb")`.

## DuckDB shims (UDFs)

`engine/shims.py::register_shims(conn)` runs at connection startup and registers four BigQuery-flavored Python UDFs on the underlying DuckDB connection:

| BigQuery function | Registered name | Implementation |
|---|---|---|
| `GENERATE_UUID()` | `generate_uuid()` | `str(uuid.uuid4())` |
| `FORMAT_DATE(fmt, date)` | `bq_format_date(fmt, date)` | Translates BigQuery format tokens (`%Y`, `%m`, `%F`, etc.) to Python `strftime` form, then `value.strftime(...)`. |
| `PARSE_DATE(fmt, str)` | `bq_parse_date(fmt, str)` | `datetime.strptime(...)` after token translation. |
| `FORMAT_TIMESTAMP(fmt, ts)` | `bq_format_timestamp(fmt, ts)` | UTC-assume on naive timestamps, then `strftime`. |
| `PARSE_TIMESTAMP(fmt, str)` | `bq_parse_timestamp(fmt, str)` | `strptime` + UTC-tag if naive. |

The token translator (`_translate_format`) supports `%Y %y %m %d %H %M %S %j %a %A %b %B %p %z %F %T %f` — uncommon tokens raise `ValueError` which surfaces as `INVALID_QUERY`.

A second class of "shim" is purely AST-level — handled in `translate.py` rather than as runtime UDFs:

- `SAFE.<fn>` → `TRY(<fn>)` (DuckDB's TRY wrapper)
- `SAFE_CAST(...)` → `TRY_CAST(...)` (sqlglot already maps this automatically)
- `APPROX_COUNT_DISTINCT` → DuckDB's native `approx_count_distinct` (sqlglot maps this)
- `APPROX_QUANTILES(x, n)` → DuckDB's `approx_quantile(x, [...])` (when applicable)
- `TO_JSON_STRING` → DuckDB's `to_json(...)::VARCHAR`

JSON operators (`JSON_EXTRACT`, `JSON_EXTRACT_SCALAR`, `JSON_VALUE`, `JSON_QUERY`) and array operations (`UNNEST(x) WITH OFFSET AS o`, `STRUCT(...)` literals) are emitted compatibly by sqlglot's BigQuery → DuckDB transpile.

## Streaming inserts (`tabledata.insertAll`)

`POST /bigquery/v2/projects/{p}/datasets/{d}/tables/{t}/insertAll` is handled by `routes/tabledata.py`. The flow:

1. Resolve the destination table from the path. Missing → request-level 404 with the standard error envelope (matches real BigQuery; no per-row `insertErrors` here).
2. For each row in `rows[]`, run `engine/coerce.py::validate_row(payload, schema)` — checks REQUIRED-field presence and unknown-field rejection. Failures populate `insertErrors[i]`.
3. If `skipInvalidRows=false` and any row failed: insert nothing; return 200 with `insertErrors[]` populated.
4. Otherwise, `INSERT INTO "p:d"."t" VALUES (?,?,...),(?,?,...),...` for surviving rows in one batched statement. Per-cell coercion runs `engine/coerce.py::row_to_values(payload, schema)` which calls `coerce_value` per field — most types pass through, but `JSON` columns get `dict`/`list` values serialized to JSON strings (DuckDB's parameter binder doesn't auto-convert).

`insertId` is read and ignored (no dedup). Streaming-buffer simulation is intentionally absent — rows are immediately visible to subsequent queries.

## Load jobs

Load jobs reach the emulator over three entry points, all of which converge on the same `LoadRunner.run_load` orchestrator:

- **`POST /upload/bigquery/v2/projects/{p}/jobs?uploadType=multipart`** — `multipart/related` body with two parts: an `application/json` job-config part and the data payload. Parsed via stdlib `email.message_from_bytes` (not `email.policy.default`, which mangles binary payloads). The data part is handed to `LoadRunner.run_load`.
- **`POST /upload/bigquery/v2/projects/{p}/jobs?uploadType=resumable`** — initiates a session. Returns 200 with `Location: <base>?upload_id=<sid>` and an empty body. The session lives in `engine/resumable.py::ResumableSessionStore` (an in-memory dict, swept by the existing service-level sweeper at `ttl=600` seconds). Subsequent `PUT?upload_id=<sid>` requests append chunks honoring `Content-Range`. While incomplete: 308 with `Range: bytes=0-<end>`. On the final chunk: run the load, return 200 + Job. `DELETE?upload_id=<sid>` drops the session idempotently.
- **`POST /bigquery/v2/projects/{p}/jobs`** with `configuration.load` (no upload body) — `routes/jobs.py::insert_job` dispatches the load runner with `data=b""` and lets it fetch from `configuration.load.sourceUris` instead.

The first two paths share `routes/uploads.py::run_load_job`, which is also called by `routes/jobs.py` for the GCS-URI path so the JobRecord persistence and `register_external` step are identical across all three entry points.

`LoadRunner.run_load` (in `engine/loads.py`) is the orchestrator:

1. Validate destination + `sourceFormat` (NDJSON or CSV; PARQUET / AVRO / ORC / DATASTORE_BACKUP rejected).
2. Resolve the source bytes:
   - If `configuration.load.sourceUris` is present, hand the list to `engine/gcs_uri.py::GcsUriFetcher.fetch_concat`. The fetcher parses each `gs://bucket/object` URI, expands glob patterns (`*`, `?`, `[...]`, `**`) by calling the GCS list-objects REST API at the configured endpoint, deduplicates resolved `(bucket, name)` pairs across the URI list while preserving order, downloads each object via `?alt=media`, and returns the concatenated bytes plus the file count (used as `statistics.load.inputFiles`). The endpoint is resolved once at service startup (`service.py::_resolve_gcs_endpoint`) in this order: `BIGQUERY_GCS_URI_ENDPOINT` → `STORAGE_EMULATOR_HOST` → `http://127.0.0.1:<gcs_port>` (loopback to the in-process gcp-local GCS service via `ctx.port_overrides`). All fetch / list / download failures map to `reason: invalid`.
   - Otherwise the inline `data` payload from the upload path is used as-is.
3. Parse the data: `_parse_ndjson` (line-by-line `json.loads`) or `_parse_csv` (stdlib `csv.reader` with dialect from `fieldDelimiter` / `quote` / `skipLeadingRows` / `nullMarker` / `encoding`).
4. Resolve the schema:
   - explicit `configuration.load.schema` if provided → `parse_table_schema`
   - else `autodetect=True` → `engine/autodetect.py::autodetect_ndjson` or `autodetect_csv`
   - else fall back to the existing table's schema from the catalog
   - else fail with `reason: invalid`
5. Enforce `createDisposition`: `CREATE_IF_NEEDED` materializes the table from the resolved schema; `CREATE_NEVER` fails with `reason: notFound`.
6. Apply `writeDisposition`: `WRITE_APPEND` is a no-op pre-step; `WRITE_TRUNCATE` runs `DELETE FROM` first; `WRITE_EMPTY` checks `SELECT 1 ... LIMIT 1` and fails with `reason: duplicate` on a non-empty target. `WRITE_TRUNCATE` is wrapped in an explicit `BEGIN ... COMMIT` (with `ROLLBACK` on failure) so a row-validation failure after the DELETE leaves the original rows intact — this matches spec §8.2's transactional guarantee.
7. Validate each row and bucket failures (REQUIRED-field violations, unknown-field rejections, CSV column-count mismatches) under `configuration.load.maxBadRecords` (default `0`). When `ignoreUnknownValues` is true, schema-unknown keys are stripped from each NDJSON row before validation and trailing extra columns are dropped from wide CSV rows. The job fails with `reason: invalid` only when the bad-record count exceeds `maxBadRecords`; otherwise the surviving rows insert and the count surfaces in `statistics.load.badRecords`. NDJSON syntax errors (lines that aren't valid JSON objects) remain fatal and bypass `maxBadRecords` because they can't be associated with a row.
8. Run the same batched `INSERT INTO ... VALUES (...),(...),...` shape as `insertAll` against the surviving rows.
9. Return a `JobRecord(job_type="LOAD", load_config=..., load_stats={inputFiles, inputFileBytes, outputRows, outputBytes, badRecords})`. The runner registers the record on the shared `JobRunner` via `register_external` so it's visible to subsequent `jobs.get` / `jobs.list` calls.

CSV cell coercion (`engine/loads.py::_coerce_csv_cell`) converts each cell to a typed Python value matching the column's declared BigQuery type:

- `INT64` / `FLOAT64` / `NUMERIC` / `BIGNUMERIC` → `int` / `float`.
- `BOOL` → `True` for `t`/`true`/`1`/`yes`/`y` (case-insensitive); `False` for `f`/`false`/`0`/`no`/`n`. Anything else is a coercion error.
- `DATE` → `datetime.date` via `date.fromisoformat`.
- `TIME` → `datetime.time` via `time.fromisoformat`.
- `DATETIME` → naive `datetime.datetime`. A timezone offset on the value is rejected (DATETIME has no timezone).
- `TIMESTAMP` → tz-aware `datetime.datetime` normalized to UTC. Accepted shapes: `YYYY-MM-DDTHH:MM:SSZ`, `... UTC`, `...+HH:MM`, or naive (assumed UTC).
- `JSON` → re-serialized after `json.loads`, so malformed JSON fails fast here rather than when DuckDB evaluates the cell.

Coercion errors raise `_LoadCoerceError`, which `_csv_to_dict_rows` catches and emits as a parse error — the row is dropped and bucketed under `maxBadRecords`.

NDJSON cell coercion (`engine/loads.py::_coerce_ndjson_cell`) is the parallel pass for NDJSON rows. Native JSON types (`int`, `float`, `bool`, `str`, `dict`, `list`, `None`) reach DuckDB as-is. The four temporal types — which JSON has no native representation for — accept the same string shapes as CSV and parse them into typed `datetime.date` / `datetime.time` / `datetime.datetime` objects via the same `_parse_datetime_naive` / `_parse_timestamp_aware` helpers. Non-string values for those columns pass through unchanged (so a Unix-timestamp number for a `TIMESTAMP` column still works). Malformed strings raise `_LoadCoerceError` and `_ndjson_coerce_rows` buckets the row under `maxBadRecords` exactly like the CSV path. JSON columns continue to be handled later in `coerce_value` (dict/list → JSON string).

## INFORMATION_SCHEMA

`engine/info_schema.py` rewrites three views at translate time:

| View | Source |
|---|---|
| `<dataset>.INFORMATION_SCHEMA.SCHEMATA` | `_gcp_local_meta.datasets` filtered by project |
| `<dataset>.INFORMATION_SCHEMA.TABLES` | `_gcp_local_meta.tables` filtered by project + dataset |
| `<dataset>.INFORMATION_SCHEMA.COLUMNS` | flattened `schema_json` column from `_gcp_local_meta.tables` |

The output schema matches BigQuery's documented column set (`table_catalog`, `table_schema`, `table_name`, `column_name`, `ordinal_position`, `is_nullable`, `data_type` in BigQuery shape — `STRING` not `VARCHAR`, etc.). Unsupported views (`JOBS_BY_USER`, `JOBS_BY_PROJECT`, `PARTITIONS`, `TABLE_OPTIONS`, `STREAMING_TIMELINE_BY_*`, `OBJECT_PRIVILEGES`) raise `UnsupportedInfoSchemaView` which surfaces as `errorResult.reason = "invalidQuery"`.

The rewrite happens as an AST pass before transpile, so the resulting DuckDB SQL queries `_gcp_local_meta` directly — there are no synthetic DuckDB views polluting per-dataset schemas.

## Job records and TTL

Job records live in two in-memory dicts on `JobRunner`:

- `_jobs: dict[(project, job_id), JobRecord]` — the records.
- `_job_ended_at: dict[(project, job_id), float]` — monotonic-clock timestamps.

A periodic sweeper (`JobRunner.sweep_expired(ttl_seconds)`) runs every 5 minutes (`asyncio.sleep(300)` in the service's `_sweeper_loop`). Records older than 1 hour (`ttl_seconds=3600`) are evicted, along with their result temp tables (`DROP TABLE IF EXISTS "_gcp_local_jobs"."_job_<job_id>"`) and the cached schema in `_job_schemas`.

Notable consequences:

- `state` is always `DONE` on response. There's no async execution — queries run synchronously inside the request handler — so the polling loop in the official Python client sees `DONE` on its first poll and exits.
- `cancel` is a no-op success: there's no in-flight work to cancel.
- Job records and result temp tables are **not** persisted across container restarts, even with `PERSIST=1`. Datasets, tables, and data are persisted; jobs are intentionally transient.
- `/_emulator/reset?service=bigquery` wipes everything: datasets, tables, data, jobs, resumable upload sessions.

## Errors

Errors split into two categories — request-shape errors (returned with the appropriate HTTP status) and query-execution errors (returned as 200 with `errorResult` populated).

**Request-shape errors** — handled by `errors.py::bigquery_error_response`, which maps internal exceptions to HTTP envelopes:

| Internal exception | HTTP | `reason` | `status` |
|---|---|---|---|
| `DatasetNotFound` / `TableNotFound` / `JobNotFound` | 404 | `notFound` | `NOT_FOUND` |
| `DatasetAlreadyExists` / `TableAlreadyExists` | 409 | `duplicate` | `ALREADY_EXISTS` |
| `InvalidName` / `UnsupportedType` / `InvalidValue` | 400 | `invalid` | `INVALID_ARGUMENT` |
| `InvalidQuery` (sqlglot parse, DuckDB binder, unsupported feature) | 400 | `invalidQuery` | `INVALID_ARGUMENT` |
| Uncaught | 500 | `internalError` | `INTERNAL` |

A second helper, `errors.py::make_error_response(code, message, reason)`, builds the same envelope shape from arbitrary `(code, message, reason)` triples. It maps known reasons to the right `status` string via `_REASON_TO_STATUS_STR` (e.g., `notFound` → `NOT_FOUND` rather than the naïve uppercase `NOTFOUND`). The upload route uses this for ad-hoc errors that don't correspond to a typed exception (multipart parse failures, unknown resumable session, unsupported `uploadType`).

**Query-execution errors** — when `JobRunner._translate` or `BigQueryConnection.execute` raises, the runner catches it and produces a `JobRecord` with `state="DONE"` and `error_result={reason, message, domain="global"}` populated. The HTTP response is **200** carrying this Job — matching real BigQuery's behavior. The Python client raises `BadRequest` / `NotFound` / etc. when it sees `errorResult`. Internal mapping inside `JobRunner.run_query`:

| Internal cause | `errorResult.reason` |
|---|---|
| `UnsupportedSql` / sqlglot parse error / `ValueError` / `InvalidQuery` | `invalidQuery` |
| `DatasetNotFound` / `TableNotFound` / `duckdb.CatalogException` | `notFound` |
| Uncaught | `internalError` |

## Tests

Unit tests under `tests/unit/services/bigquery/` — one file per concern: `test_routes_*.py`, `test_engine_*.py` (`test_jobs`, `test_loads_*`, `test_translate`, `test_shims`, `test_autodetect_*`, `test_resumable`, `test_coerce`, `test_load_dispositions`), `test_storage`, `test_models*`, `test_errors`, `test_info_schema`, `test_types`, `test_names`. Most tests use `BigQueryConnection.in_memory()` plus the real `BigQueryStorage` and `JobRunner` — only the FastAPI `TestClient` is mocked-style.

Integration tests at `tests/integration/test_bigquery_integration.py` drive the real `google-cloud-bigquery` Python client against an in-process emulator (booted by the `emulator` fixture in `tests/integration/conftest.py`). The integration suite covers dataset/table CRUD, query + DML round-trips, streaming inserts, INFORMATION_SCHEMA, error paths, multi-page result iteration via `to_dataframe()`, plus six load-job cases including a ~6 MiB synthetic NDJSON payload that forces the official client onto the resumable upload path.

## Browser UI consumer

`src/gcp_local/core/ui_api/bigquery.py` exposes a small, internal JSON API at `/_emulator/ui-api/v1/bigquery/...` that the bundled SPA calls. It is **not** part of the BigQuery wire contract and clients must not rely on it. The router reads and writes the same `BigQueryStorage` and `JobRunner` instances the public REST routes use — there is no shadow state. A table created by the official `google-cloud-bigquery` client appears in the UI immediately, and a `CREATE TABLE` issued from the UI's query console is visible to clients on port 9050 without any sync step.

The UI surface is shaped for browser display rather than wire fidelity:

- **Schemas** are serialized with `snake_case` keys (`dataset_id`, `table_schema`, `last_modified_time`) instead of the `camelCase` BQ wire format. This keeps the SPA's TypeScript types ergonomic without forcing the wire layer to change.
- **Cell values** in `preview` and `queries` responses are converted by `_cell_to_jsonable`: primitives pass through, `Decimal`/`bytes`/`date`/`time`/`datetime` are stringified (bytes use base64), and `list`/`tuple`/`dict` recurse. The wire surface keeps emitting BQ's `{"v": ...}` envelope; the ui-api collapses it to bare JSON for display.
- **Queries** are executed by reusing `JobRunner.run_query()` so error mapping stays consistent (`invalidQuery` / `notFound` / `internalError`). The job runs synchronously, the UI immediately reads the first page via `JobRunner.read_page`, and the Job stays in the `JobRunner._jobs` cache for the standard 1-hour TTL — the UI does not eagerly evict it. The query endpoint always returns `200`; runtime errors come back inline as `result.error` (mirroring real BigQuery's behavior of stashing failures in `errorResult` rather than raising HTTP 5xx).
- **Project discovery** is derived from the catalog — `GET /bigquery/projects` runs `SELECT project, count(*) FROM _gcp_local_meta.datasets GROUP BY project`. Projects only show up once they have at least one dataset; users open arbitrary project IDs through the "Open project" dialog to seed the first dataset.

For the broader UI architecture (build pipeline, dev loop, recipe for adding a new service surface), see [`docs/development/ui.md`](../development/ui.md).

## Internals-level limitations

These are the gaps a consumer should know about. User-visible "what's not emulated" lives in [`docs/services/bigquery.md`](../services/bigquery.md); this list is internals-flavored.

- **Single DuckDB connection** — all execution is serialized through one connection plus a single-worker thread executor. Concurrent queries from multiple clients will block on each other; this is fine for emulator workloads but won't scale to real concurrency testing.
- **`statistics.totalBytesProcessed = 0`** — DuckDB has no equivalent to BigQuery's bytes-scanned metric. Dashboards or assertions that gate on a non-zero value will need to tolerate `0`.
- **No Parquet / Avro / ORC source formats** — load jobs only accept NDJSON and CSV (both inline and `gs://` URIs).
- **Time-zone handling** — DuckDB's `TIMESTAMP WITH TIME ZONE` stores in UTC and returns UTC. There's no client-side timezone conversion.
- **Job records are transient** — not persisted across container restarts, even with `PERSIST=1`. `jobs.list` only returns jobs from the current process lifetime.
- **`cancel` is a no-op success** — queries run synchronously inside the request handler, so there's nothing to cancel by the time the cancel arrives.
- **`legacySQL`** is rejected. So is anything in the banned-features regex (`ML.*`, `ST_*`, `DECLARE`, `BEGIN`, `EXCEPTION`, `FOR SYSTEM_TIME AS OF`).
