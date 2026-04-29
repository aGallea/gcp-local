# gcp-local — BigQuery Load Jobs (Inline NDJSON + CSV) Design

**Date:** 2026-04-26
**Status:** Draft for review
**Scope:** v1.x increment on the existing BigQuery service. Adds inline-payload load jobs.
**Parent service design:** [2026-04-25-gcp-local-bigquery-design.md](./2026-04-25-gcp-local-bigquery-design.md)

## 1. Overview

This document specifies the **BigQuery load-job upload endpoints** for `gcp-local`. The existing BigQuery service supports `tabledata.insertAll` for streaming inserts and `jobs.insert` for query jobs; this increment adds the third write path real BigQuery exposes — load jobs — with a deliberately narrow scope (inline payloads only).

Success criterion: `google-cloud-bigquery`'s `client.load_table_from_json(...)` and `client.load_table_from_file(...)` (with `source_format=NEWLINE_DELIMITED_JSON` or `CSV`) work unchanged against the emulator, including under the official client's automatic switch from multipart to resumable uploads as payload size grows.

Motivation: the maestro-evals project currently patches `BigQueryRunner.run_load_job` to fall back to `insert_rows_json` because the emulator lacks a load-job endpoint. Landing this feature lets that shim be deleted, leaving only the unavoidable `get_default_client` `AnonymousCredentials` patch.

## 2. Scope

### In scope

- `POST /upload/bigquery/v2/projects/{p}/jobs?uploadType=multipart` — single-shot multipart upload.
- `POST /upload/bigquery/v2/projects/{p}/jobs?uploadType=resumable` — initiate resumable session; `PUT` chunks; complete on final chunk.
- Source formats: `NEWLINE_DELIMITED_JSON`, `CSV`.
- `writeDisposition`: `WRITE_APPEND` (default), `WRITE_TRUNCATE`, `WRITE_EMPTY`.
- `createDisposition`: `CREATE_IF_NEEDED` (default), `CREATE_NEVER`.
- Schema sources: explicit `configuration.load.schema`, `autodetect=True`, or fall back to existing-table schema.
- New `LOAD` job type appearing in `jobs.get` / `jobs.list` with the same TTL and `state=DONE`-on-completion semantics as query jobs.

### Out of scope (unchanged from parent BQ spec §2 unless overridden)

- **GCS-URI loads** (`configuration.load.sourceUris: ["gs://..."]`) — *deferred at the time this spec was written; subsequently shipped*. NDJSON and CSV `gs://` loads (including globs and multi-URI lists) are now handled via `engine/gcs_uri.py::GcsUriFetcher`, which fetches over HTTP from a configurable endpoint (defaults to the loopback in-process GCS service). See `docs/architecture/bigquery.md` "Load jobs" for the current flow. Binary formats (Parquet/Avro/ORC) and Datastore backups remain out of scope.
- **Source formats:** `PARQUET`, `AVRO`, `ORC`, `DATASTORE_BACKUP`. Reject with `errorResult.reason = "invalid"`.
- **`uploadType=media`** (raw single-shot). Rejected with 400; the official client never uses this for jobs.
- Copy jobs, extract jobs, ML model imports.
- Real load-job statistics fidelity beyond `inputFiles`, `inputFileBytes`, `outputRows`, `outputBytes`, `badRecords`.

## 3. URL surface

The BigQuery service today serves `/bigquery/v2/...`. Real BigQuery uses a second prefix `/upload/bigquery/v2/...` for media uploads, and the official client constructs upload URLs against that prefix. The same FastAPI app gains a second router mounted at the upload prefix.

| Method | Path | Query | Purpose |
|---|---|---|---|
| `POST` | `/upload/bigquery/v2/projects/{project}/jobs` | `uploadType=multipart` | Single-shot upload. Body is `multipart/related` with metadata + data parts. Response: 200 + Job resource. |
| `POST` | `/upload/bigquery/v2/projects/{project}/jobs` | `uploadType=resumable` | Initiate session. Body is the JSON Job resource (no data). Response: 200, empty body, `Location: <full URL>?upload_id=<sid>`. |
| `PUT` | `/upload/bigquery/v2/projects/{project}/jobs` | `upload_id=<sid>` | Append chunk. Honors `Content-Range: bytes <a>-<b>/<total\|*>`. Response: 308 + `Range: bytes=0-<b>` while incomplete; 200 + Job resource on the chunk that completes the upload. |
| `DELETE` | `/upload/bigquery/v2/projects/{project}/jobs` | `upload_id=<sid>` | Cancel a session. Response: 200 + empty body. (Sessions are also reaped by TTL.) |

Unsupported `uploadType` values (`media`, anything else) → 400 with the standard error envelope and `reason = "invalid"`.

## 4. Package layout (additions on the existing service)

```
src/gcp_local/services/bigquery/
  routes/
    uploads.py            # NEW — multipart + resumable HTTP handlers
  engine/
    loads.py              # NEW — LoadRunner: parse → validate → execute
    autodetect.py         # NEW — schema inference for NDJSON + CSV
    coerce.py             # NEW — shared row-validation + value-coercion helpers
  models.py               # MODIFIED — JobRecord gains load_config / load_stats
  app.py                  # MODIFIED — mount uploads router
  routes/tabledata.py     # MODIFIED — switch to engine/coerce.py helpers
  routes/jobs.py          # MODIFIED — _job_to_api branches on job_type for LOAD
```

### 4.1 Targeted in-area refactor

`tabledata.py` currently defines `_validate_row`, `_coerce_value`, and `_row_to_values` privately. The load path needs the same logic. We extract them to `engine/coerce.py` (no behavior change) and import from both `tabledata.py` and `loads.py`. This is the only refactor; everything else is purely additive.

## 5. Multipart and resumable parsing

### 5.1 Multipart (`uploadType=multipart`)

Request body: `Content-Type: multipart/related; boundary=<b>` with two parts in order:
1. `Content-Type: application/json; charset=UTF-8` — the Job resource (`{"jobReference": ..., "configuration": {"load": {...}}}`).
2. `Content-Type: application/octet-stream` (NDJSON) or `text/csv` — the data payload.

Parsing strategy: stdlib `email.parser.BytesParser` constructs a `Message` from the prepended `Content-Type` header + the raw body. We walk `.walk()`, skipping the multipart container; the first leaf with JSON content type gives the metadata, the next leaf gives the data bytes. Other orderings or part counts raise `MultipartParseError` → 400.

Why stdlib over `python-multipart`: `python-multipart` targets `multipart/form-data` (HTML forms), not `multipart/related` (RFC 2387) which BigQuery uses. `email.parser` is the same code path google-resumable-media uses on the client side.

### 5.2 Resumable (`uploadType=resumable`)

In-memory `dict[session_id, ResumableUpload]` on the service:

```python
@dataclass
class ResumableUpload:
    session_id: str
    project: str
    job_config: dict           # parsed from the init POST body
    declared_total: int | None # from X-Upload-Content-Length, if sent
    received_total: int        # running total of bytes appended
    chunks: bytearray          # accumulated data
    last_write: float          # unix ts; for TTL
```

**Init (`POST?uploadType=resumable`):**
- Body parses as JSON. Build `ResumableUpload` with `session_id = uuid4().hex`, `declared_total = int(headers.get("X-Upload-Content-Length") or 0) or None`. Store in dict.
- Response: 200, empty body, `Location: <scheme>://<host>/upload/bigquery/v2/projects/{project}/jobs?upload_id=<session_id>`.

**Append (`PUT?upload_id=<sid>`):**
- Look up session; missing → 410 `notFound`.
- Parse `Content-Range: bytes <start>-<end>/<total|*>`. If `<start> != session.received_total`, return 400 `invalid` (out-of-order chunk; the client never does this in normal flow but we surface it cleanly).
- Append the body bytes to `session.chunks`; advance `received_total = <end>+1`.
- If `<total>` is `*` (size unknown until final chunk), respond 308 + `Range: bytes=0-<end>`.
- If `<total>` is numeric and `<end>+1 < <total>`, respond 308 + `Range: bytes=0-<end>`.
- If `<end>+1 == <total>` (final chunk), hand `chunks` + `job_config` to `LoadRunner`, persist the resulting `JobRecord`, drop the session entry, respond 200 + Job resource.

**Cancel (`DELETE?upload_id=<sid>`):**
- Drop the session entry. Always 200 (idempotent).

**TTL:** 10 minutes since `last_write`. Implementation: extend the existing `JobRunner` sweeper (which already runs every 5 minutes for job records) to also walk resumable sessions. Adding a second async loop is unnecessary churn.

## 6. Source-format parsing

### 6.1 NDJSON

Iterate `data.splitlines()`, skip empty lines, `json.loads(line)` each. Each parsed object is a row payload structurally identical to `tabledata.insertAll`'s `row.json` body, so it flows through the shared `engine/coerce.py` helpers with no further transformation.

`json.JSONDecodeError` on any line aborts the load with `errorResult.reason = "invalid"`, message `"Failed to parse JSON: line <n>: <error>"`.

### 6.2 CSV

Stdlib `csv.reader` with a dialect derived from `configuration.load`:

| Load field | csv dialect | Default |
|---|---|---|
| `fieldDelimiter` | `delimiter` | `","` |
| `quote` | `quotechar` | `'"'` |
| `allowQuotedNewlines` | (csv.reader handles this when `quoting=QUOTE_MINIMAL`) | `False` (we always honor quoted newlines — CSV reader does anyway; the BQ flag is only meaningful for streaming parsers) |
| `nullMarker` | post-parse cell substitution → Python `None` | `""` (i.e. an empty cell becomes None) |
| `skipLeadingRows` | drop the first N rows from the iterator | `0` |
| `encoding` | decode the upload bytes (`UTF-8`, `ISO-8859-1`) | `"UTF-8"` |

Column order on a CSV load: the active schema's column order (whether explicit, autodetected, or pulled from an existing table). After parsing, each CSV row is mapped to `{column_name: cell_value}` and runs through the shared coercion path identical to NDJSON.

CSV-specific autodetect (`skipLeadingRows ≥ 1` plus `autodetect=True`): row 0 supplies column names; type inference walks rows 1..min(100, end). See §7.2.

## 7. Schema resolution

Run at load start, before any data parsing or table creation:

1. **Explicit:** if `configuration.load.schema.fields` is set, use it verbatim. Validate against the existing table if one exists (column-name set must be a subset; column types must match exactly — REPEATED/REQUIRED modes must agree). Mismatch → `errorResult.reason = "invalid"`.
2. **Autodetect:** if `autodetect=True` and no explicit schema, run `engine/autodetect.py` (§7.1, §7.2) over the parsed rows. The result is treated as authoritative.
3. **Existing-table fallback:** if neither explicit nor autodetect, but the table already exists, use the existing table's schema.
4. **None of the above:** fail the job with `errorResult.reason = "invalid"`, message `"Load configuration must specify schema or autodetect"`.

### 7.1 NDJSON autodetect

Walk the first 100 parsed objects (or all of them if fewer). Per top-level key:
- Track the set of observed Python types across non-null values.
- Map to a BigQuery type using widening rules:

| Observed | Inferred |
|---|---|
| only `bool` | `BOOL` |
| only `int` | `INT64` |
| `int` ∪ `float` | `FLOAT64` |
| any `str` | `STRING` (most permissive — covers dates and timestamps too; matches BQ's behavior for ambiguous string-shaped data) |
| `dict` | `RECORD` (recurse into nested fields) |
| `list` | `REPEATED` of the element-level inference (recurse) |

All inferred fields default to `mode = "NULLABLE"` (or `"REPEATED"` when the value is a list). Empty payload → fail with `errorResult.reason = "invalid"`, message `"Cannot autodetect schema from empty input"`.

### 7.2 CSV autodetect

Row 0 (when `skipLeadingRows ≥ 1`) supplies column names. Per column, sniff up to 100 data rows in order:

| Pattern | Inferred |
|---|---|
| empty cell | (skip — does not constrain) |
| `^-?\d+$` for all sniffed values | `INT64` |
| `^-?\d+(\.\d+)?$` for all sniffed values, at least one with `.` | `FLOAT64` |
| `^(true|false)$` (case-insensitive) for all sniffed values | `BOOL` |
| `^\d{4}-\d{2}-\d{2}$` | `DATE` |
| matches RFC3339 `^\d{4}-\d{2}-\d{2}T...` | `TIMESTAMP` |
| anything else | `STRING` |

If `skipLeadingRows = 0` and `autodetect=True`, BigQuery's behavior is to synthesize column names `string_field_0`, `string_field_1`, ... — we match that, and run the same per-column type sniff over rows 0..min(100, end).

## 8. Disposition handling

### 8.1 Create disposition

After schema resolution, before write:

- `CREATE_IF_NEEDED` (default): if the table does not exist, create it via the existing `BigQueryStorage.create_table(...)` path using the resolved schema. The catalog row is written and the DuckDB schema/table is materialized just like a `tables.insert` API call.
- `CREATE_NEVER`: if the table does not exist, fail the job with `errorResult.reason = "notFound"`, message `"Not found: Table <project>:<dataset>.<table>"`.

### 8.2 Write disposition

After the table exists:

- `WRITE_APPEND` (default): no pre-step. Insert appended to existing rows.
- `WRITE_TRUNCATE`: emit `DELETE FROM "<project>:<dataset>"."<table>"` before the load INSERT. Both statements run inside an explicit `BEGIN ... COMMIT` block — DuckDB's transactional semantics guarantee a failed insert leaves the original rows intact.
- `WRITE_EMPTY`: emit `SELECT 1 FROM "<project>:<dataset>"."<table>" LIMIT 1`. If any row exists, fail the job with `errorResult.reason = "duplicate"`, message `"Already Exists: Table <name> is not empty"`. Otherwise proceed as `WRITE_APPEND`. The table being empty but with a different schema is permitted.

## 9. Load execution

After schema resolution, parse, and disposition setup, the load runs the same batched INSERT shape used by `tabledata.insertAll`:

```sql
INSERT INTO "<project>:<dataset>"."<table>" VALUES (?,?,...),(?,?,...),...;
```

Parameters are produced by `engine/coerce.py::row_to_values(payload, schema)` — the same helper insertAll uses. Per-row validation errors (`required field missing`, `unknown field`, CSV column-count mismatch) are aggregated and bucketed under `configuration.load.maxBadRecords` (default `0`); rows beyond that count abort the load with `errorResult.reason = "invalid"`, while accepted bad rows surface in `statistics.load.badRecords`. This differs from `insertAll`'s `insertErrors[]` shape (per-row return) but matches real BigQuery load-job behavior. *Note: §11 of this doc originally said load jobs were all-or-nothing; that was the v1 simplification, now superseded by `maxBadRecords` support — see §17.*

DuckDB execution errors during the INSERT itself surface as `errorResult.reason = "invalidQuery"` (binder/type errors) or `"invalid"` (constraint violations) following the parent spec's error mapping (§6.5).

After successful load, populate `JobRecord.load_stats`:

```python
{
  "inputFiles": "1",
  "inputFileBytes": str(len(data)),
  "outputRows": str(len(rows)),
  "outputBytes": str(len(data)),  # we don't separately track post-write bytes; mirror input
  "badRecords": "0"
}
```

Counts are strings to match real BQ wire format.

## 10. Job model integration

### 10.1 `JobRecord` extensions

```python
@dataclass
class JobRecord:
    # ... existing fields ...
    job_type: str              # "QUERY" | "DML" | "LOAD"   (NEW: "LOAD")
    load_config: dict | None = None
    load_stats: dict | None = None
```

Existing fields continue to work for QUERY/DML; LOAD jobs leave `sql=""`, `statement_type=""`, `total_rows=len(rows_loaded)` (int, mirroring `outputRows`), `destination_table=(project, dataset, table)`.

### 10.2 `_job_to_api` branching

Current code emits `configuration.query` and `statistics.query` unconditionally. Refactor to branch:

```python
if rec.job_type == "LOAD":
    body["configuration"] = {"jobType": "LOAD", "load": rec.load_config}
    body["statistics"]["load"] = rec.load_stats
else:  # QUERY / DML
    body["configuration"] = {"jobType": rec.job_type, "query": {"query": rec.sql, ...}}
    body["statistics"]["query"] = {"totalBytesProcessed": ..., "statementType": ...}
```

`destinationTable` continues to attach for LOAD jobs (it's the load target).

### 10.3 Lifecycle

- TTL: 1 hour from `end_time`. Same sweeper as query jobs.
- `state`: always `"DONE"` on response, matching the existing synchronous-but-shaped pattern (parent §6.1).
- `jobs.list`: includes LOAD jobs alongside QUERY/DML.
- `jobs.cancel`: returns success without effect, same as query jobs.
- `/_emulator/reset?service=bigquery`: also clears resumable sessions.

## 11. Errors

| Cause | Surface | `reason` | HTTP |
|---|---|---|---|
| Multipart parse failure (missing parts, malformed boundary) | sync error | `invalid` | 400 |
| Unsupported `uploadType` | sync error | `invalid` | 400 |
| Resumable session not found | sync error | `notFound` | 410 |
| `Content-Range` mismatch / out-of-order chunk | sync error | `invalid` | 400 |
| Resumable session expired (TTL) | sync error | `notFound` | 410 |
| Unsupported `sourceFormat` | job error | `invalid` | 200 + `errorResult` |
| Schema missing (no explicit, no autodetect, no existing table) | job error | `invalid` | 200 + `errorResult` |
| Autodetect on empty payload | job error | `invalid` | 200 + `errorResult` |
| `CREATE_NEVER` + missing table | job error | `notFound` | 200 + `errorResult` |
| `WRITE_EMPTY` + non-empty table | job error | `duplicate` | 200 + `errorResult` |
| Per-row validation failure (any row) | job error | `invalid` (aggregated, first 5 in `errors[]`) | 200 + `errorResult` |
| NDJSON parse failure on any line | job error | `invalid` | 200 + `errorResult` |
| CSV column count mismatch | job error | `invalid` | 200 + `errorResult` |
| DuckDB execution error | job error | `invalidQuery` / `invalid` | 200 + `errorResult` |
| Explicit schema disagrees with existing-table schema | job error | `invalid` | 200 + `errorResult` |

Job-level errors return a 200 response with a Job resource where `status.state="DONE"` and `status.errorResult` is populated; the official client raises the appropriate `google.api_core.exceptions` subclass when it sees `errorResult`. This is consistent with parent spec §6.5.

## 12. Testing

### 12.1 Unit tests

| File | Coverage |
|---|---|
| `tests/unit/bigquery/test_uploads_multipart.py` | parse well-formed multipart; reject malformed (missing data part, wrong boundary, wrong content type on metadata part); pass parsed result through to LoadRunner with mocked storage |
| `tests/unit/bigquery/test_uploads_resumable.py` | init returns `Location`; PUT chunks accumulate; final chunk completes; out-of-order chunk → 400; expired session → 410; DELETE drops session; sweeper TTL behavior |
| `tests/unit/bigquery/test_loads_ndjson.py` | row parsing, validation, batched INSERT generation, empty-payload error |
| `tests/unit/bigquery/test_loads_csv.py` | dialect parameters (`fieldDelimiter`, `quote`, `nullMarker`, `skipLeadingRows`, `encoding`), column-count mismatch error |
| `tests/unit/bigquery/test_autodetect_ndjson.py` | type widening (BOOL → INT → FLOAT → STRING), nested RECORD inference, REPEATED inference |
| `tests/unit/bigquery/test_autodetect_csv.py` | per-column type sniffing, header-row + no-header-row paths |
| `tests/unit/bigquery/test_load_dispositions.py` | matrix of (CREATE_IF_NEEDED, CREATE_NEVER) × (WRITE_APPEND, WRITE_TRUNCATE, WRITE_EMPTY) × (table-missing, table-empty, table-non-empty); verify post-conditions and error reasons |
| `tests/unit/bigquery/test_coerce.py` | the extracted shared helper — kept as a regression test that the refactor didn't change insertAll behavior |

### 12.2 Integration tests

Six new cases extending `tests/integration/test_bigquery_integration.py`. The fixture is unchanged (the existing `emulator` fixture already boots `bigquery`).

1. **`load_table_from_json` with explicit schema** — load 100 rows including JSON, REPEATED, and NUMERIC fields; query back via `client.query(...)` and verify row count + values.
2. **`load_table_from_json` with autodetect to non-existent table** — `LoadJobConfig(autodetect=True)`; verify table is created with the expected schema (via `client.get_table`) and rows are readable.
3. **`load_table_from_file` with CSV + explicit schema + `skipLeadingRows=1`** — `StringIO(csv_text)` → load → query round-trip; verify type coercion (int/float/date columns).
4. **`WRITE_TRUNCATE`** — populate table via insertAll, then load with `WRITE_TRUNCATE`; row count post-load equals only the load payload size (truncate happened).
5. **`WRITE_EMPTY` against non-empty** — populate table, then attempt load with `WRITE_EMPTY`; assert `google.api_core.exceptions.Conflict` (or whichever the client raises for `duplicate`) is raised.
6. **Resumable upload forced** — synthesize a ~6 MiB NDJSON payload (well past `_DEFAULT_CHUNKSIZE` so the official client switches to resumable); load and verify success. This proves the resumable handler works end-to-end under the official client.

### 12.3 Documentation tests

`docs/services/bigquery.md` gains a "Load jobs" section with a working `load_table_from_json` example and a CSV `load_table_from_file` example. The integration suite asserts both examples run as written (copy the snippets into a test that imports from the doc string or replicate verbatim).

## 13. HTTP / admin surface

`Service.health()` unchanged. `reset_state()` extended to clear resumable sessions in addition to its current behavior. `jobs.list` includes LOAD jobs.

## 14. Dependencies

**No new runtime deps.** `email.parser`, `csv`, `json`, `uuid`, `dataclasses` are stdlib.

`google-cloud-bigquery` (already in dev extras) carries `google-resumable-media` transitively, which the integration tests exercise on the client side; no direct dependency from the emulator.

## 15. Documentation updates

- `docs/services/bigquery.md` — new "Load jobs" section with NDJSON + CSV examples, autodetect example, write-disposition examples.
- `README.md` — add "inline NDJSON + CSV load jobs" to the BigQuery feature list, and remove the corresponding line from the BigQuery "Out of v1" section.

## 16. Migration path for maestro-evals

Out of scope for this spec but recorded so the loop closes:

1. Land this feature; cut a new gcp-local image tag.
2. In maestro-evals, bump the gcp-local image reference; remove `shims.py::_replace_run_load_job_with_streaming_inserts` and its registration in `local_bq_shim.py`. Verify the smoke flow.
3. Update `project_maestro_evals_gcp_local` memory: only the `get_default_client` AnonymousCredentials shim remains.

## 17. Additional supported `configuration.load` flags

- **`maxBadRecords`** (default `0`): per-row validation failures up to this count do not abort the job; the failed rows are dropped and `load_stats.badRecords` reflects the count. Beyond this count, the job aborts with `errorResult.reason = "invalid"`.
- **`ignoreUnknownValues`** (default `False`): when `True`, unknown-field validation errors on row payloads are silently dropped instead of contributing to the bad-record count.
- **`encoding`** (CSV only, default `"UTF-8"`): `UTF-8` and `ISO-8859-1` accepted; any other value → `errorResult.reason = "invalid"`.

## 18. Open items

- **Aborted resumable sessions accumulate memory** — bounded by TTL (10 min) and the sweeper; no max-session cap in v1. Acceptable for emulator use.
- **Schema mode `REPEATED` with NDJSON null** — null at a REPEATED position is treated as empty list (`[]`), matching BQ behavior.
- **Concurrent loads to the same table** — no explicit lock; serialized through the single DuckDB connection's executor. Real BQ allows concurrent loads with last-writer-wins on metadata; we match that incidentally.

## 19. Non-goals recap

This spec does not describe: GCS-URI loads, Parquet/Avro/ORC/Datastore source formats, copy/extract jobs, schema relaxation (`schemaUpdateOptions`), partition decorators on the destination table, hive-partitioned source layouts, ML model imports, federated tables, external table refresh.
