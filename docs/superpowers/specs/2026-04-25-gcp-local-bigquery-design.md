# gcp-local — BigQuery Service Design

**Date:** 2026-04-25
**Status:** Draft for review
**Scope:** Third v1 service — BigQuery. First REST service that wraps a query engine.
**Core design:** [2026-04-24-gcp-local-core-design.md](./2026-04-24-gcp-local-core-design.md)

## 1. Overview

This document specifies the **BigQuery emulator** — the third real service in `gcp-local`. Success criterion: the official `google-cloud-bigquery` Python client library works unchanged against the emulator for the dataset/table lifecycle, synchronous + async query, DML, and streaming inserts.

The BigQuery service is REST-only (the official client speaks REST + Discovery; gRPC is a separate Storage Read/Write API and out of v1). It is the first service in `gcp-local` that wraps a SQL execution engine, so it picks up `duckdb` and `sqlglot` as new runtime deps.

## 2. Scope (v1)

### In scope

- **Dataset lifecycle:** `datasets.insert`, `datasets.get`, `datasets.list`, `datasets.update`, `datasets.patch`, `datasets.delete`
- **Table lifecycle:** `tables.insert`, `tables.get`, `tables.list`, `tables.update`, `tables.patch`, `tables.delete`. Schema CRUD (REQUIRED/NULLABLE/REPEATED, RECORD/STRUCT, ARRAY).
- **Query path:**
  - `jobs.query` (synchronous endpoint)
  - `jobs.insert` with `QueryJobConfiguration` (async-shaped; completes synchronously, see §6)
  - `jobs.get`, `jobs.list`, `jobs.cancel`
  - `jobs.getQueryResults` with `pageToken` paging
- **DML:** `INSERT` / `UPDATE` / `DELETE` / `MERGE` executed via DuckDB (after sqlglot translation)
- **Streaming inserts:** `tabledata.insertAll` — direct `INSERT INTO`, immediately visible (§7)
- **Project namespacing:** `projects/<project>/datasets/<dataset>/tables/<table>` is the primary key; different projects can hold same dataset/table independently
- **In-memory and on-disk storage backends** (opt-in disk via `PERSIST=1`)
- **REST error envelope** matching real BigQuery responses

### Out of v1 (deferred)

- **Load jobs** (`jobs.insert` with `LoadJobConfiguration`) — no CSV/JSON/Parquet/Avro ingestion from `gs://`. Defer to a v1.x cross-service iteration once GCS↔BQ wiring is built.
- **Copy jobs** and **extract jobs**
- **Table snapshots, clones, time travel** (`FOR SYSTEM_TIME AS OF …`)
- **Materialized views, scheduled queries, routines (UDFs / stored procs), models**
- **Row-level access policies, column-level security, dataset access controls, IAM**
- **Storage Read API and Storage Write API** (these are gRPC and a separate scope)
- **`INFORMATION_SCHEMA.JOBS_BY_*`, `PARTITIONS`, `TABLE_OPTIONS`, `STREAMING_TIMELINE`, `OBJECT_PRIVILEGES`** — only `TABLES`, `COLUMNS`, `SCHEMATA` are exposed
- **ML.\***, most **ST_\*** geo functions, **scripting / procedural SQL**, recursive-CTE edge cases — per core design's "known v1 gaps"
- **Partitioning execution** (DDL accepted and stored on table metadata, ignored at query time)
- **Clustering execution** (DDL accepted, ignored at query time)
- **Streaming-buffer simulation** (eventual visibility, `cannotModifyStreamingBuffer`) — punt to v2 fault injection
- **`insertId` deduplication** on streaming inserts — accepted in request, ignored
- **Legacy SQL** (`useLegacySql: true`) — rejected with `INVALID_QUERY`

## 3. Service architecture

### 3.1 Package layout

```
src/gcp_local/services/bigquery/
  __init__.py                  # exports BigQueryService
  service.py                   # BigQueryService (implements core Service protocol)
  app.py                       # FastAPI app + route wiring
  routes/
    datasets.py                # /projects/{p}/datasets/* handlers
    tables.py                  # /projects/{p}/datasets/{d}/tables/* handlers
    jobs.py                    # /projects/{p}/jobs/* handlers + queryResults
    tabledata.py               # /projects/{p}/datasets/{d}/tables/{t}/insertAll
  models.py                    # DatasetRecord, TableRecord, FieldSchema, JobRecord
  storage.py                   # Storage protocol + InMemoryStorage + DiskStorage
  engine/
    __init__.py
    connection.py              # DuckDB connection + lifecycle (single conn or pool)
    naming.py                  # logical (project, dataset, table) → DuckDB schema/table
    translate.py               # sqlglot BigQuery → DuckDB transpile + AST tweaks
    shims.py                   # registers BQ-specific UDFs on DuckDB connection
    types.py                   # BQ TableSchema ↔ DuckDB types
    info_schema.py             # INFORMATION_SCHEMA.{TABLES,COLUMNS,SCHEMATA} views
    jobs.py                    # JobRunner: execute query, materialize results, page
  errors.py                    # exception → REST error-envelope mapping
  names.py                     # resource-name parsers and URL helpers
```

### 3.2 Port and transport

Default **9050**. Override via `BIGQUERY_EMULATOR_PORT` through the existing `port_overrides` machinery. The official Python client honors `BIGQUERY_EMULATOR_HOST=localhost:9050` and routes there with insecure-channel HTTP.

REST app is FastAPI, consistent with GCS. The service registers a single `uvicorn` listener on its port, mounted alongside (not under) the admin app.

### 3.3 Connection from client code

```python
import os
from google.cloud import bigquery

os.environ["BIGQUERY_EMULATOR_HOST"] = "localhost:9050"
client = bigquery.Client(project="my-project", credentials=None)
```

(README will spell out the `credentials=None` + `client_options={"api_endpoint": ...}` variant for users on client-library versions that don't honor `BIGQUERY_EMULATOR_HOST` cleanly.)

## 4. Data model

### 4.1 Resource names

| Resource | Form |
|---|---|
| Dataset | `projects/<project>/datasets/<dataset_id>` |
| Table | `projects/<project>/datasets/<dataset_id>/tables/<table_id>` |
| Job | `projects/<project>/jobs/<job_id>` |

`<project>` allowed: `[a-z][a-z0-9-]{4,28}[a-z0-9]` (real GCP rule); we validate loosely (`[a-z0-9-]{1,63}`) and accept anything that fits.
`<dataset_id>` and `<table_id>`: `[A-Za-z0-9_]{1,1024}` (real BQ rule, conservative cap).
`<job_id>`: `[A-Za-z0-9_-]{1,1024}`.

### 4.2 Records

```python
@dataclass
class FieldSchema:
    name: str
    type: str            # "STRING", "INT64", "FLOAT64", "BOOL", "BYTES",
                         # "TIMESTAMP", "DATE", "TIME", "DATETIME", "JSON",
                         # "NUMERIC", "BIGNUMERIC", "RECORD"
    mode: str            # "NULLABLE" | "REQUIRED" | "REPEATED"
    fields: list[FieldSchema] | None  # only for RECORD


@dataclass
class TableRecord:
    project: str
    dataset_id: str
    table_id: str
    schema: list[FieldSchema]
    create_time: str       # RFC3339
    last_modified_time: str
    description: str | None
    labels: dict[str, str]
    # Accepted but ignored (stored as-is for round-trip fidelity):
    time_partitioning: dict | None
    range_partitioning: dict | None
    clustering: dict | None


@dataclass
class DatasetRecord:
    project: str
    dataset_id: str
    create_time: str
    last_modified_time: str
    description: str | None
    labels: dict[str, str]
    location: str          # accepted; default "US"; not enforced
    default_table_expiration_ms: int | None  # accepted; not enforced


@dataclass
class JobRecord:
    project: str
    job_id: str
    job_type: str          # "QUERY" | "DML"
    state: str             # "DONE" (always — see §6)
    create_time: str
    start_time: str
    end_time: str
    user_email: str
    statement_type: str    # "SELECT" | "INSERT" | "UPDATE" | "DELETE" | "MERGE" | ...
    sql: str
    destination_table: tuple[str, str, str] | None  # (project, dataset_id, table_id) — for SELECTs, points at the temp result table in `_gcp_local_jobs`; None for DML
    total_rows: int
    total_bytes_processed: int
    error_result: dict | None  # BQ-shaped error if query failed
    errors: list[dict]
```

### 4.3 Type mapping (BQ ↔ DuckDB)

Per Q3-A — lean fidelity, documented gaps:

| BQ type | DuckDB type | Notes |
|---|---|---|
| `STRING` | `VARCHAR` | |
| `BYTES` | `BLOB` | |
| `INT64` | `BIGINT` | |
| `FLOAT64` | `DOUBLE` | |
| `BOOL` | `BOOLEAN` | |
| `NUMERIC` | `DECIMAL(38, 9)` | BQ NUMERIC(38,9) |
| `BIGNUMERIC` | `DECIMAL(38, 18)` | 20 integer digits + 18 fractional, vs BQ BIGNUMERIC's 38+38 — documented gap |
| `DATE` | `DATE` | |
| `TIME` | `TIME` | |
| `TIMESTAMP` | `TIMESTAMP WITH TIME ZONE` | |
| `DATETIME` | `TIMESTAMP` | DuckDB has no native distinction; round-trip via stored field metadata (see below) |
| `JSON` | `JSON` | |
| `RECORD` / `STRUCT` | `STRUCT(...)` | nested |
| `ARRAY<T>` (`mode=REPEATED`) | `T[]` (DuckDB LIST) | |
| `GEOGRAPHY` | (rejected at schema-create) | `INVALID_ARGUMENT` |
| `INTERVAL`, `RANGE` | (rejected) | |

**`TIMESTAMP` vs `DATETIME` round-trip:** DuckDB conflates these at column-storage time (both look like `TIMESTAMP` in `information_schema.columns`). We keep the BQ-declared type in our own `TableRecord.schema` and use that — not DuckDB's column type — when serializing query results back to clients. The DuckDB column type is an internal storage detail.

### 4.4 Multi-project namespacing

Project IDs are accepted as-is and become the first segment of the schema name (§5.1). No project allow-list, no validation against an emulator config. Consistent with Secret Manager.

## 5. Storage layout

### 5.1 Logical → DuckDB mapping (Q2-A)

One DuckDB database file holds everything across all projects.

| Logical | DuckDB |
|---|---|
| `<project>.<dataset>.<table>` | schema `"<project>:<dataset>"`, table `"<table>"` |
| Job-result temp tables | schema `"_gcp_local_jobs"`, table `"_job_<job_id>"` |
| Service metadata | schema `"_gcp_local_meta"`, tables `datasets`, `tables` (catalog) |

The catalog schema (`_gcp_local_meta`) holds the authoritative `DatasetRecord` / `TableRecord` rows (one row per resource, all metadata fields as columns or a single JSON column). DuckDB schemas exist alongside their catalog rows, but the catalog is the source of truth for fields DuckDB doesn't preserve (BQ field modes, field descriptions, partitioning config, labels, timestamps).

The `:` separator is unambiguous because real BQ project IDs forbid `:` and dataset IDs forbid `:` (allowed dataset chars are `[A-Za-z0-9_]`). DuckDB identifier rules accept `:` inside double-quoted identifiers, and we always quote schema names in emitted SQL. The form intentionally mirrors BQ's own legacy `project:dataset.table` notation. (We assert these rules in `naming.py` and reject names violating them with `INVALID_ARGUMENT`.)

### 5.2 In-memory backend

`duckdb.connect(":memory:")`. One connection for the service lifetime; SQL serialization handles concurrency (DuckDB allows multiple cursors on one connection). For CPU-bound queries, requests offload `conn.execute(...)` calls to a thread executor (per core design §3.1).

`reset()` drops every non-system schema and rebuilds the catalog.

### 5.3 On-disk backend

Single DuckDB file at `/data/bigquery.duckdb` (the path declared in core design §4.2). `PERSIST=1` switches the connection from `:memory:` to the file path. WAL is enabled (DuckDB default for files).

**Job records and result temp tables are not persisted across restarts** — see §6.4.

### 5.4 Catalog schema initialization

On service start, `engine.connection` ensures `_gcp_local_meta` exists with the catalog tables and `_gcp_local_jobs` exists for transient job-result tables. Both are created with `CREATE SCHEMA IF NOT EXISTS`.

## 6. Job model

### 6.1 Synchronous-but-shaped

Per core design: every `jobs.insert` runs the work synchronously inside the request handler. The response carries a real-shaped `Job` resource with `status.state = "DONE"`, populated `statistics`, and `jobReference`. `jobs.get` returns the stored record. The Python client's polling loop sees `DONE` on its first poll and exits.

`jobs.cancel` returns success but does nothing — there is no in-flight work to cancel.

### 6.2 `jobs.insert` (Query)

1. Parse `configuration.query.query` as BigQuery SQL via `sqlglot.parse_one(sql, dialect="bigquery")`.
2. Reject `useLegacySql: true` with `INVALID_QUERY`.
3. Apply BQ-specific AST tweaks (`engine/translate.py`):
   - Rewrite three-part names `` `project.dataset.table` `` to schema-qualified `"project:dataset"."table"`.
   - Resolve wildcard tables (`` `project.dataset.events_*` ``) by enumerating matching tables in the catalog and emitting a `UNION ALL` of the matches.
   - `SAFE.<fn>(args)` → `TRY(<fn>(args))`.
   - Strip partitioning DDL clauses on `CREATE TABLE` (accepted, stored on metadata, not executed).
4. Transpile to DuckDB: `node.sql(dialect="duckdb")`.
5. Execute against the DuckDB connection.
6. **For SELECT statements:** materialize results into `_gcp_local_jobs._job_<job_id>` via `CREATE TEMP TABLE ... AS <translated SQL>`. Compute `total_rows` via `SELECT COUNT(*)`. Result schema (column names + BQ types) is captured from the SELECT's projection list (using sqlglot's analyzer + the catalog) and stored on the JobRecord. `destination_table` points at the temp table using a synthetic project sentinel (`"_gcp_local"`, `"_gcp_local_jobs"`, `"_job_<job_id>"`); not user-visible — clients use `jobReference.jobId` to fetch results.
7. **For DML:** execute directly; capture `affected_row_count` from DuckDB and surface as `numDmlAffectedRows` in `statistics.query`.
8. Build `JobRecord` and persist to in-memory job map.

### 6.3 Result paging (Q4-α)

`jobs.getQueryResults?maxResults=N&pageToken=T`:

- Default `maxResults` = 10000 (matches Python client's default request size).
- `pageToken` is an opaque base64-encoded integer offset (we don't pretend it's a row marker).
- Implementation: `SELECT * FROM _gcp_local_jobs._job_<job_id> LIMIT N OFFSET decode(pageToken)`.
- Response carries `pageToken` for the next page if `offset + N < total_rows`, else omitted.
- Rows serialized to BQ's `f`/`v` row format using `TableRecord.schema` (not DuckDB's column types) for type fidelity (§4.3 `TIMESTAMP`/`DATETIME` distinction).

`jobs.query` (synchronous endpoint): runs steps 1–7 above, then returns the first page directly in the response. If `total_rows > maxResults`, includes `pageToken` so the client transparently switches to `getQueryResults` for subsequent pages.

### 6.4 Retention

- **Job records and result temp tables: in-memory only.** Lost on container restart, even with `PERSIST=1`. Datasets/tables/data are persisted; jobs are not.
- **TTL: 1 hour** from `end_time`. A background `asyncio` task sweeps expired job records (drops the temp table, removes the dict entry). Sweeper runs every 5 minutes.
- **`/_emulator/reset?service=bigquery`** wipes datasets, tables, data, AND all job records/temp tables.
- **`jobs.list`** returns only non-expired jobs.

### 6.5 Errors during query execution

Any sqlglot parse error, DuckDB execution error, or AST-tweak failure is captured into the job's `errorResult` + `errors[]`. `jobs.insert` still returns `200` with a Job in `state=DONE` and `errorResult` populated — this matches real BQ. The Python client raises `google.api_core.exceptions.BadRequest` etc. when it sees `errorResult`. `jobs.query` returns the same shape.

| Internal cause | BQ `errorResult.reason` | HTTP equivalent (for sync errors) |
|---|---|---|
| sqlglot parse failure | `invalidQuery` | 400 |
| Reference to non-existent table | `notFound` | 404 |
| Type-mismatch / DuckDB binder error | `invalidQuery` | 400 |
| DuckDB constraint violation | `invalid` | 400 |
| Unknown / uncaught DuckDB error | `internalError` | 500 |
| `useLegacySql: true` | `invalidQuery` | 400 |
| `GEOGRAPHY` schema field at create | `invalid` | 400 |

## 7. Write path

### 7.1 `tabledata.insertAll` (streaming inserts)

Per Q5-A. Each request body is `{rows: [{insertId?: str, json: {...}}, ...], skipInvalidRows?: bool, ignoreUnknownValues?: bool}`.

Request handling:
1. Resolve target table from URL path. **If missing → request-level 404 with envelope `{error: {code: 404, ..., errors: [{reason: "notFound", ...}]}}`** — matches real BQ; no per-row `insertErrors`.
2. For each row, validate the row JSON against `TableRecord.schema` (required-field presence, type coercion, REPEATED → array, RECORD → nested object). Failures populate `insertErrors[i]`.
3. If `skipInvalidRows=false` and any row failed: do not insert anything; return 200 with `insertErrors[]` populated.
4. Otherwise (all valid, or `skipInvalidRows=true` and at least some valid): `INSERT INTO "<project>:<dataset>"."<table>" VALUES (...)` for the surviving rows in one batch. Failed-row entries still surface in `insertErrors[]`.

`insertId` is read from the request and ignored (no dedup, per Q5-A).

Response shape matches BQ exactly: `{kind: "bigquery#tableDataInsertAllResponse", insertErrors?: [...]}`.

### 7.2 DML (`INSERT`/`UPDATE`/`DELETE`/`MERGE`)

Submitted via the query path (§6.2). DuckDB handles all four. `MERGE` requires DuckDB ≥ 0.10 (current stable). After execution, the job's `statistics.query.numDmlAffectedRows` and `statistics.query.dmlStats` (`{insertedRowCount, updatedRowCount, deletedRowCount}`) are populated from DuckDB's affected-row counts.

DML changes are immediately visible to subsequent queries in the same connection (DuckDB ACID semantics). No streaming-buffer simulation.

## 8. Read path: `INFORMATION_SCHEMA`

Implemented as virtual views resolved at query-translation time, not as physical DuckDB views (we don't want to pollute every dataset schema with synthetic view objects). When sqlglot's analyzer sees a reference to `<project>.<dataset>.INFORMATION_SCHEMA.<view>`, the AST tweak in `engine/translate.py` rewrites it to a SELECT over the catalog tables in `_gcp_local_meta`.

### 8.1 Supported views

| View | Source |
|---|---|
| `<dataset>.INFORMATION_SCHEMA.SCHEMATA` | `_gcp_local_meta.datasets` filtered by project |
| `<dataset>.INFORMATION_SCHEMA.TABLES` | `_gcp_local_meta.tables` filtered by project + dataset |
| `<dataset>.INFORMATION_SCHEMA.COLUMNS` | flattened from `_gcp_local_meta.tables.schema_json` |

Returned column shape matches the BQ documentation: `table_catalog`, `table_schema`, `table_name`, `column_name`, `ordinal_position`, `is_nullable`, `data_type` (BQ-shape, e.g. `STRING`, not DuckDB-shape `VARCHAR`), `is_partitioning_column`, `clustering_ordinal_position`, etc.

### 8.2 Unsupported views

`JOBS_BY_USER`, `JOBS_BY_PROJECT`, `JOBS_BY_ORGANIZATION`, `PARTITIONS`, `TABLE_OPTIONS`, `STREAMING_TIMELINE_BY_*`, `OBJECT_PRIVILEGES`: a reference returns `errorResult.reason = "invalidQuery"` with message `"INFORMATION_SCHEMA view '<name>' is not supported in gcp-local v1"`. Documented in README.

## 9. SQL translation and shims

### 9.1 Pipeline (per query)

1. `sqlglot.parse_one(sql, dialect="bigquery")` → BQ AST.
2. Apply project-specific AST passes (`engine/translate.py`):
   - Three-part name rewrite (`` `p.d.t` `` → `"p:d"."t"`).
   - Wildcard-table expansion to `UNION ALL` of matches.
   - `SAFE.<fn>(...)` → `TRY(<fn>(...))`.
   - `INFORMATION_SCHEMA` view resolution.
   - Partitioning DDL strip on `CREATE TABLE`.
3. `node.sql(dialect="duckdb")` → DuckDB SQL string.
4. Execute on DuckDB connection.
5. (Result-row pass) Re-shape result rows from DuckDB native types to BQ JSON wire format using `TableRecord.schema`.

### 9.2 Function shims (Q6-A)

Registered on the DuckDB connection at startup via `CREATE OR REPLACE FUNCTION` or via Python UDFs (`conn.create_function`):

| BQ function | Strategy |
|---|---|
| `GENERATE_UUID()` | DuckDB Python UDF returning `uuid.uuid4().hex` formatted with hyphens |
| `FORMAT_DATE`, `FORMAT_TIMESTAMP` | Python UDF translating the BQ format string (e.g. `%Y-%m-%d`) to DuckDB's `strftime`-compatible tokens |
| `PARSE_DATE`, `PARSE_TIMESTAMP` | Python UDF using `datetime.strptime` after BQ-format-token translation |
| `SAFE_CAST` | Native DuckDB `TRY_CAST` (sqlglot transpiles automatically) |
| `SAFE.<fn>` prefix | Rewritten to `TRY(<fn>)` in AST pass (not as UDF) |
| `APPROX_COUNT_DISTINCT` | Native DuckDB `approx_count_distinct` (sqlglot already maps) |
| `APPROX_QUANTILES(x, n)` | Rewritten to `approx_quantile(x, [1.0/n, 2.0/n, ..., 1.0])` |
| `TO_JSON_STRING` | DuckDB `to_json(...)::VARCHAR` |
| `JSON_EXTRACT_SCALAR`, `JSON_EXTRACT`, `JSON_VALUE`, `JSON_QUERY` | DuckDB JSON operators |
| `UNNEST(x) WITH OFFSET AS o` | sqlglot already emits compatible DuckDB |
| `STRUCT(...)` constructor | sqlglot already emits DuckDB struct literal |

The format-string translator covers the common BQ tokens (`%Y %m %d %H %M %S %z %f %j %a %A %b %B %p`); uncommon tokens raise a clear `INVALID_QUERY` error pointing at the docs.

### 9.3 Documented gaps

Per core design — explicitly NOT supported:

- `ML.*` functions (any reference → `INVALID_QUERY`)
- `ST_*` geography functions
- Scripting / procedural SQL (`DECLARE`, `BEGIN…EXCEPTION…END`, `LOOP`, `IF…ELSEIF`)
- Recursive CTE corner cases (basic `WITH RECURSIVE` works in DuckDB; some BQ-only patterns may not)
- Time-travel queries (`FOR SYSTEM_TIME AS OF …`)

A reference to one of these surfaces as `errorResult.reason = "invalidQuery"` with a message naming the unsupported feature.

## 10. Errors

### 10.1 REST envelope

All error responses use the GCP REST envelope:

```json
{
  "error": {
    "code": 404,
    "message": "Not found: Table my-project:my_dataset.users",
    "errors": [{"reason": "notFound", "message": "...", "domain": "global"}],
    "status": "NOT_FOUND"
  }
}
```

Built by a shared helper in `bigquery/errors.py` that mirrors `core/errors.py`'s envelope helper. Status codes:

| Internal exception | HTTP | `reason` |
|---|---|---|
| `DatasetNotFound` / `TableNotFound` / `JobNotFound` | 404 | `notFound` |
| `DatasetAlreadyExists` / `TableAlreadyExists` | 409 | `duplicate` |
| `InvalidName` / `InvalidSchema` / `UnsupportedType` (`GEOGRAPHY` etc.) | 400 | `invalid` |
| `InvalidQuery` (sqlglot parse, DuckDB binder, unsupported feature) | 400 | `invalidQuery` |
| `InvalidValue` (row payload type mismatch) | 400 | `invalid` |
| Uncaught | 500 | `internalError` |

Query-execution errors take a different path: §6.5. The job is `state=DONE` with `errorResult` populated; the HTTP response is 200.

## 11. Cross-service interactions

**None in v1.** BigQuery is a leaf service. Load jobs from `gs://` (which would consume StateHub events or read GCS storage directly) are deferred per §2.

When load jobs land in v1.x, they will use direct backend access (calling into the GCS service's `Storage` protocol via the registry), not StateHub events. Documented here so the BQ↔GCS coupling story is not invented twice.

## 12. Testing

### 12.1 Unit tests

- `test_naming.py` — logical → DuckDB schema mapping; rejects project/dataset names containing `:` (separator collision)
- `test_types.py` — BQ schema → DuckDB DDL round-trip; reject GEOGRAPHY/INTERVAL/RANGE
- `test_translate.py` — sqlglot AST passes: three-part-name rewrite, wildcard expansion, `SAFE.` rewrite, INFORMATION_SCHEMA resolution, partitioning DDL strip
- `test_shims.py` — each registered shim function with sample inputs (UUID format, FORMAT_DATE tokens)
- `test_storage_memory.py` + `test_storage_disk.py` — symmetric CRUD suite for datasets/tables, parameterized over both backends
- `test_jobs.py` — JobRecord lifecycle, TTL sweep, paging math
- `test_errors.py` — exception → REST envelope mapping
- `test_info_schema.py` — TABLES/COLUMNS/SCHEMATA shape; unsupported views error correctly
- `test_insert_all.py` — row validation, partial-row-failure response shape

### 12.2 Integration tests

Real `google-cloud-bigquery` driving the emulator. Single file `tests/integration/test_bigquery_integration.py`:

1. **Dataset CRUD** — `create_dataset` → `get_dataset` → `update_dataset(labels=…)` → `delete_dataset`
2. **Table CRUD** — create with full schema (STRUCT, ARRAY, NUMERIC); get; update description; delete
3. **Streaming insert + query round-trip** — `insert_rows_json` → `query("SELECT * FROM …")` → row counts + values match
4. **`SELECT` + `to_dataframe()`** — multi-page result. Forces pagination by passing `max_results` on `RowIterator` (or by populating ~25K rows and using the default page size). Verifies `getQueryResults` paging works under the client's iterator.
5. **DML** — `INSERT … VALUES`, `UPDATE … SET … WHERE`, `DELETE FROM … WHERE`, `MERGE INTO …` — affected-row counts match
6. **`STRUCT` + `ARRAY`** — round-trip a row with nested record + repeated field; `to_arrow()` types preserved
7. **`JSON` column** — write `{"a": 1}` literal; query with `JSON_EXTRACT_SCALAR(j, "$.a")`
8. **Wildcard table** — `SELECT * FROM \`p.d.events_*\`` returns union of `events_2024_01`, `events_2024_02`
9. **`INFORMATION_SCHEMA.TABLES`** — listing finds tables created above
10. **Error path** — `client.query("SELECT * FROM nonexistent_table")` raises `google.api_core.exceptions.NotFound`
11. **Error path** — `client.query("SELECT FROM where")` (parse error) raises `google.api_core.exceptions.BadRequest` with reason `invalidQuery`
12. **`jobs.list`** — created jobs above appear in listing

Test fixture extends the existing `emulator` pattern: boots the emulator with `gcs`, `secret_manager`, `bigquery` registered; sets `BIGQUERY_EMULATOR_HOST` to `localhost:<port>`; constructs `bigquery.Client(project="test-project", credentials=AnonymousCredentials())`.

### 12.3 Core integration test update

Existing `tests/integration/test_core_end_to_end.py` is updated to assert `bigquery` shows up in `/_emulator/services` after this work.

## 13. HTTP / admin surface

Admin API unchanged. `Service.health()` returns `HealthStatus(name="bigquery", ok=True, listening_on=[("rest", 9050)])`. `reset_state()` drops every non-system schema, clears the in-memory job map, and re-runs catalog initialization.

## 14. Dependencies summary

**New runtime (added in `pyproject.toml`):**
- `duckdb>=0.10` — query engine
- `sqlglot>=23.0` — BigQuery → DuckDB translation
- (uvicorn/fastapi already present)

**New dev:**
- `google-cloud-bigquery>=3.17` already present in `[project.optional-dependencies].dev`
- `db-dtypes>=1.2` — added to `[project.optional-dependencies].dev` so `to_dataframe()` resolves NUMERIC/BIGNUMERIC types reliably across client versions
- `pyarrow>=15` — added explicitly so `to_arrow()` test is deterministic across client versions

## 15. Open items

Handled with explicit defaults; noted here for awareness:

- **DuckDB connection model:** single connection serialized via thread executor for v1. If a real concurrency issue surfaces, switch to a per-request connection or DuckDB's experimental connection pool. Not blocking.
- **`statistics.query.totalBytesProcessed`:** real BQ reports byte-scanned; DuckDB doesn't expose an equivalent metric. **Default: report `0`.** Clients and dashboards that gate on this need to tolerate 0; documented in README.
- **`jobs.list` filtering** (`projection`, `stateFilter`, `parentJobId`): **Default: support `projection=minimal|full` and `stateFilter`; ignore `parentJobId` (no scripting in v1).**
- **Time-zone handling for `TIMESTAMP`:** DuckDB `TIMESTAMP WITH TIME ZONE` stores in UTC and returns UTC. Matches BQ. No client-side TZ shifting.
- **`labels` and `description` on datasets/tables:** stored on the catalog row; `update`/`patch` honor `update_mask` for individual fields. Real BQ `etag` semantics (optimistic concurrency on writes): **Default: accept any etag; return SHA1 of catalog row JSON as etag on read** (mirrors Secret Manager §11).
- **DuckDB version pinning:** `>=0.10` lets us absorb minor releases; if a release breaks `MERGE` or sqlglot transpile we pin tighter in v1.x.

## 16. Non-goals recap

This spec does not describe: load jobs, copy jobs, extract jobs, table snapshots/clones, time-travel queries, materialized views, scheduled queries, routines/UDFs/stored procs, BQ ML, geography functions, scripting/procedural SQL, Storage Read/Write APIs, IAM, dataset access controls, fault injection / streaming buffer simulation, legacy SQL.
