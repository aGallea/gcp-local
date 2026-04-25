# gcp-local BigQuery Load Jobs (Inline NDJSON + CSV) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline-payload load-job support to the existing BigQuery service so `google-cloud-bigquery`'s `client.load_table_from_json(...)` and `client.load_table_from_file(..., source_format=NEWLINE_DELIMITED_JSON|CSV)` work unchanged against the emulator. Covers multipart and resumable uploads, NDJSON + CSV source formats, full write/create disposition handling, explicit schema + autodetect, and a new `LOAD` job type. No GCS-URI loads, no Parquet/Avro/ORC.

**Architecture:** A new FastAPI router mounted at the `/upload/bigquery/v2` prefix handles `POST` (multipart and resumable init) and `PUT` (resumable chunks). Multipart bodies are parsed via stdlib `email.parser`. Resumable session state is held in an in-memory dict on the service, swept by the existing 5-minute job-sweeper task. A new `LoadRunner` parses the data part (NDJSON line-by-line or CSV via stdlib `csv`), resolves the schema from explicit/autodetect/existing-table, applies `createDisposition` + `writeDisposition`, and runs the same batched `INSERT` shape that `tabledata.insertAll` uses today. Row validation/coercion helpers extracted from `routes/tabledata.py` into a shared `engine/coerce.py` are reused by both write paths. The `JobRecord` model gains `load_config` / `load_stats` fields and `routes/jobs.py::_job_to_api` branches on `job_type`.

**Tech Stack:** Python 3.13, FastAPI/uvicorn (existing), stdlib `email.parser` for multipart, stdlib `csv` for CSV, stdlib `json` for NDJSON, DuckDB (existing query engine), `google-cloud-bigquery` (test-only driver, already in dev extras).

**Spec:** `docs/superpowers/specs/2026-04-26-gcp-local-bigquery-load-jobs-design.md`

**Branch:** `bigquery-load-jobs` (create at start of Task 1). All commits land on this branch; when all tasks pass, open a PR to `master`.

**Commit policy:** Commits allowed in this session. Use `python -m pip` (not bare `pip`). Do not bypass signing/hooks. Trailer on every commit (HEREDOC):
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## File structure

**New files:**

```
src/gcp_local/services/bigquery/
  engine/
    coerce.py                      # NEW — shared row validation + value coercion
    autodetect.py                  # NEW — NDJSON + CSV schema inference
    loads.py                       # NEW — LoadRunner: parse → validate → execute
    resumable.py                   # NEW — ResumableUpload session storage
  routes/
    uploads.py                     # NEW — multipart + resumable HTTP handlers

tests/unit/services/bigquery/
  test_coerce.py                   # NEW — regression for refactored helpers
  test_autodetect_ndjson.py        # NEW
  test_autodetect_csv.py           # NEW
  test_loads_ndjson.py             # NEW
  test_loads_csv.py                # NEW
  test_load_dispositions.py        # NEW
  test_resumable.py                # NEW
  test_routes_uploads_multipart.py # NEW
  test_routes_uploads_resumable.py # NEW
```

**Modified files:**

```
src/gcp_local/services/bigquery/
  models.py                        # JobRecord: add load_config, load_stats; update job_to_dict / job_from_dict
  routes/tabledata.py              # import from engine/coerce instead of local helpers
  routes/jobs.py                   # _job_to_api branches on job_type for LOAD
  app.py                           # mount uploads_router; pass LoadRunner + ResumableStore
  service.py                       # construct LoadRunner + ResumableStore; sweep resumables in sweeper loop

tests/integration/
  test_bigquery_integration.py     # 6 new test cases for load jobs

docs/services/bigquery.md          # new "Load jobs" section
README.md                          # remove "Load jobs" from BigQuery's not-emulated list
```

---

## Task 1: Branch + extract shared coerce helpers (refactor)

Goal: lift the row validation and value coercion helpers out of `routes/tabledata.py` into `engine/coerce.py` so the new `LoadRunner` can reuse them. Pure refactor; insertAll behavior must remain identical.

**Files:**
- Create: `src/gcp_local/services/bigquery/engine/coerce.py`
- Create: `tests/unit/services/bigquery/test_coerce.py`
- Modify: `src/gcp_local/services/bigquery/routes/tabledata.py` (replace local helpers with imports)

- [ ] **Step 1: Create branch**

```bash
git switch -c bigquery-load-jobs
```

- [ ] **Step 2: Write the failing test**

`tests/unit/services/bigquery/test_coerce.py`:

```python
"""Regression tests for shared row-validation + coercion helpers (Task 1)."""

import json

from gcp_local.services.bigquery.engine.coerce import (
    coerce_value,
    row_to_values,
    validate_row,
)
from gcp_local.services.bigquery.models import FieldSchema


def _f(name: str, type_: str, mode: str = "NULLABLE", fields=None) -> FieldSchema:
    return FieldSchema(name=name, type=type_, mode=mode, fields=fields)  # type: ignore[arg-type]


def test_validate_row_required_field_missing() -> None:
    schema = [_f("id", "INT64", "REQUIRED"), _f("name", "STRING")]
    errors = validate_row({"name": "alice"}, schema)
    assert errors == ["required field 'id' is missing"]


def test_validate_row_unknown_field() -> None:
    schema = [_f("id", "INT64", "REQUIRED")]
    errors = validate_row({"id": 1, "extra": "?"}, schema)
    assert errors == ["unknown field 'extra'"]


def test_validate_row_happy_path() -> None:
    schema = [_f("id", "INT64", "REQUIRED")]
    assert validate_row({"id": 1}, schema) == []


def test_coerce_value_passes_scalar_through() -> None:
    assert coerce_value(42, _f("id", "INT64")) == 42


def test_coerce_value_serializes_json_dict() -> None:
    out = coerce_value({"a": 1}, _f("payload", "JSON"))
    assert json.loads(out) == {"a": 1}


def test_coerce_value_serializes_repeated_json() -> None:
    out = coerce_value([{"a": 1}, {"b": 2}], _f("payloads", "JSON", "REPEATED"))
    assert [json.loads(x) for x in out] == [{"a": 1}, {"b": 2}]


def test_coerce_value_none_passthrough() -> None:
    assert coerce_value(None, _f("id", "INT64")) is None


def test_row_to_values_orders_by_schema() -> None:
    schema = [_f("id", "INT64", "REQUIRED"), _f("name", "STRING"), _f("payload", "JSON")]
    out = row_to_values({"name": "x", "id": 1, "payload": {"k": "v"}}, schema)
    assert out[0] == 1
    assert out[1] == "x"
    assert json.loads(out[2]) == {"k": "v"}


def test_row_to_values_missing_optional_is_none() -> None:
    schema = [_f("id", "INT64", "REQUIRED"), _f("name", "STRING")]
    assert row_to_values({"id": 1}, schema) == [1, None]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/services/bigquery/test_coerce.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gcp_local.services.bigquery.engine.coerce'`

- [ ] **Step 4: Write minimal implementation**

`src/gcp_local/services/bigquery/engine/coerce.py`:

```python
"""Shared row-validation + value-coercion helpers (spec §6, §9).

Used by both ``routes/tabledata.py`` (streaming inserts) and
``engine/loads.py`` (load jobs). Lifted from a private helper block in
tabledata so the load path can reuse the exact same coercion semantics
without code duplication.
"""

import json
from typing import Any

from gcp_local.services.bigquery.models import FieldSchema


def validate_row(payload: dict[str, Any], schema: list[FieldSchema]) -> list[str]:
    """Return a list of error messages for the row; empty means valid."""
    errors: list[str] = []
    by_name = {f.name: f for f in schema}
    for f in schema:
        if f.mode == "REQUIRED" and payload.get(f.name) is None:
            errors.append(f"required field {f.name!r} is missing")
    for key in payload:
        if key not in by_name:
            errors.append(f"unknown field {key!r}")
    return errors


def coerce_value(value: Any, field: FieldSchema) -> Any:
    """Adapt one cell to a form DuckDB will accept for the column's type.

    Real BigQuery's `tabledata.insertAll` and load jobs both let clients send
    a native dict / list for a `JSON` column; DuckDB's parameter binder
    doesn't auto-convert those, so we serialize to a JSON string here.
    REPEATED JSON columns are handled by serializing each element.
    """
    if value is None:
        return None
    if field.type == "JSON":
        if field.mode == "REPEATED":
            return [json.dumps(v) if isinstance(v, dict | list) else v for v in value]
        if isinstance(value, dict | list):
            return json.dumps(value)
    return value


def row_to_values(payload: dict[str, Any], schema: list[FieldSchema]) -> list[Any]:
    return [coerce_value(payload.get(f.name), f) for f in schema]
```

- [ ] **Step 5: Run the new tests**

Run: `python -m pytest tests/unit/services/bigquery/test_coerce.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Update `routes/tabledata.py` to use the shared helpers**

Replace the existing private helpers with imports. The full file becomes:

`src/gcp_local/services/bigquery/routes/tabledata.py`:

```python
"""Streaming inserts: /bigquery/v2/projects/{p}/datasets/{d}/tables/{t}/insertAll."""

from typing import Any

from fastapi import APIRouter, Body

from gcp_local.services.bigquery.engine.coerce import row_to_values, validate_row
from gcp_local.services.bigquery.errors import bigquery_error_response
from gcp_local.services.bigquery.models import TableRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    duckdb_table_qualname,
    validate_dataset_id,
    validate_project_id,
    validate_table_id,
)
from gcp_local.services.bigquery.storage import BigQueryStorage, TableNotFound


def build_router(storage: BigQueryStorage) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post("/{project}/datasets/{dataset_id}/tables/{table_id}/insertAll")
    async def insert_all(
        project: str,
        dataset_id: str,
        table_id: str,
        body: dict[str, Any] = Body(...),  # noqa: B008
    ) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            validate_table_id(table_id)
            table: TableRecord = await storage.get_table(project, dataset_id, table_id)
        except (TableNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

        rows_in = body.get("rows") or []
        skip_invalid = bool(body.get("skipInvalidRows", False))

        insert_errors: list[dict[str, Any]] = []
        valid_rows: list[list[Any]] = []
        for i, row in enumerate(rows_in):
            payload = row.get("json") or {}
            errs = validate_row(payload, table.schema)
            if errs:
                insert_errors.append(
                    {
                        "index": i,
                        "errors": [
                            {"reason": "invalid", "message": e, "domain": "global"} for e in errs
                        ],
                    }
                )
                continue
            valid_rows.append(row_to_values(payload, table.schema))

        if insert_errors and not skip_invalid:
            return {
                "kind": "bigquery#tableDataInsertAllResponse",
                "insertErrors": insert_errors,
            }

        if valid_rows:
            qualname = duckdb_table_qualname(project, dataset_id, table_id)
            placeholders = ",".join(
                "(" + ",".join(["?"] * len(table.schema)) + ")" for _ in valid_rows
            )
            params: list[Any] = [v for row in valid_rows for v in row]
            await storage.connection.execute(
                f"INSERT INTO {qualname} VALUES {placeholders}", params
            )

        if insert_errors:
            return {
                "kind": "bigquery#tableDataInsertAllResponse",
                "insertErrors": insert_errors,
            }
        return {"kind": "bigquery#tableDataInsertAllResponse"}

    return router
```

- [ ] **Step 7: Run the full bigquery test suite to confirm no regression**

Run: `python -m pytest tests/unit/services/bigquery/ -v`
Expected: PASS (all existing tests + the 8 new coerce tests).

- [ ] **Step 8: Commit**

```bash
git add src/gcp_local/services/bigquery/engine/coerce.py \
        tests/unit/services/bigquery/test_coerce.py \
        src/gcp_local/services/bigquery/routes/tabledata.py
git commit -m "$(cat <<'EOF'
refactor(bigquery): extract shared row-coercion helpers to engine/coerce

Lift validate_row, coerce_value, row_to_values from routes/tabledata.py
into engine/coerce.py so the upcoming load-job path can reuse the exact
same JSON-column coercion semantics as streaming inserts.

Pure refactor — insertAll behavior is unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Extend `JobRecord` for `LOAD` jobs and branch `_job_to_api`

Goal: add `load_config` and `load_stats` fields to `JobRecord`, update the dict round-trip helpers, and make `_job_to_api` emit the right `configuration.load` / `statistics.load` shape for `LOAD` jobs while keeping `QUERY`/`DML` jobs unchanged.

**Files:**
- Modify: `src/gcp_local/services/bigquery/models.py`
- Modify: `src/gcp_local/services/bigquery/routes/jobs.py`
- Create: `tests/unit/services/bigquery/test_models_load.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_models_load.py`:

```python
"""JobRecord LOAD-type round-trip + API serialization (Task 2)."""

from gcp_local.services.bigquery.models import JobRecord, job_from_dict, job_to_dict
from gcp_local.services.bigquery.routes.jobs import _job_to_api


def _load_record(**overrides) -> JobRecord:
    base = dict(
        project="p",
        job_id="j1",
        job_type="LOAD",
        state="DONE",
        create_time="1000",
        start_time="1000",
        end_time="2000",
        user_email="local@gcp-local.invalid",
        statement_type="",
        sql="",
        destination_table=("p", "d", "t"),
        total_rows=3,
        total_bytes_processed=0,
        error_result=None,
        errors=[],
        load_config={
            "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "sourceFormat": "NEWLINE_DELIMITED_JSON",
            "writeDisposition": "WRITE_APPEND",
            "createDisposition": "CREATE_IF_NEEDED",
        },
        load_stats={
            "inputFiles": "1",
            "inputFileBytes": "120",
            "outputRows": "3",
            "outputBytes": "120",
            "badRecords": "0",
        },
    )
    base.update(overrides)
    return JobRecord(**base)


def test_job_record_load_round_trip() -> None:
    rec = _load_record()
    raw = job_to_dict(rec)
    assert raw["load_config"]["sourceFormat"] == "NEWLINE_DELIMITED_JSON"
    rec2 = job_from_dict(raw)
    assert rec2 == rec


def test_job_to_api_load_branches_configuration_and_statistics() -> None:
    rec = _load_record()
    body = _job_to_api(rec)
    assert body["configuration"]["jobType"] == "LOAD"
    assert body["configuration"]["load"]["sourceFormat"] == "NEWLINE_DELIMITED_JSON"
    assert "query" not in body["configuration"]
    assert body["statistics"]["load"]["outputRows"] == "3"
    assert "query" not in body["statistics"]
    # Destination table still attaches.
    assert body["configuration"]["load"]["destinationTable"]["tableId"] == "t"


def test_job_to_api_query_unchanged() -> None:
    rec = JobRecord(
        project="p",
        job_id="j2",
        job_type="QUERY",
        state="DONE",
        create_time="1000",
        start_time="1000",
        end_time="2000",
        user_email="local@gcp-local.invalid",
        statement_type="SELECT",
        sql="SELECT 1",
        destination_table=("_gcp_local", "_gcp_local_jobs", "_job_j2"),
        total_rows=0,
        total_bytes_processed=0,
        error_result=None,
        errors=[],
    )
    body = _job_to_api(rec)
    assert body["configuration"]["query"]["query"] == "SELECT 1"
    assert "load" not in body["configuration"]
    assert body["statistics"]["query"]["statementType"] == "SELECT"
    assert "load" not in body["statistics"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/services/bigquery/test_models_load.py -v`
Expected: FAIL — `JobRecord.__init__() got an unexpected keyword argument 'load_config'`

- [ ] **Step 3: Update `JobRecord` and dict helpers**

Edit `src/gcp_local/services/bigquery/models.py`:

Replace the `JobRecord` dataclass with:

```python
@dataclass
class JobRecord:
    project: str
    job_id: str
    job_type: str  # "QUERY" | "DML" | "LOAD"
    state: str  # always "DONE" in v1
    create_time: str
    start_time: str
    end_time: str
    user_email: str
    statement_type: str
    sql: str
    destination_table: tuple[str, str, str] | None
    total_rows: int
    total_bytes_processed: int
    error_result: dict[str, Any] | None
    errors: list[dict[str, Any]] = dc_field(default_factory=list)
    load_config: dict[str, Any] | None = None
    load_stats: dict[str, Any] | None = None
```

Replace `job_from_dict` with:

```python
def job_from_dict(raw: dict[str, Any]) -> JobRecord:
    dest = raw.get("destination_table")
    if dest is not None:
        dest = (dest[0], dest[1], dest[2])
    return JobRecord(
        project=raw["project"],
        job_id=raw["job_id"],
        job_type=raw["job_type"],
        state=raw["state"],
        create_time=raw["create_time"],
        start_time=raw["start_time"],
        end_time=raw["end_time"],
        user_email=raw["user_email"],
        statement_type=raw["statement_type"],
        sql=raw["sql"],
        destination_table=dest,
        total_rows=raw["total_rows"],
        total_bytes_processed=raw["total_bytes_processed"],
        error_result=raw.get("error_result"),
        errors=list(raw.get("errors") or []),
        load_config=raw.get("load_config"),
        load_stats=raw.get("load_stats"),
    )
```

(`job_to_dict` is unchanged — `dataclasses.asdict` already includes the new fields.)

- [ ] **Step 4: Update `_job_to_api` to branch on `job_type`**

Edit `src/gcp_local/services/bigquery/routes/jobs.py`. Replace the `_job_to_api` function with:

```python
def _job_to_api(rec: JobRecord) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "bigquery#job",
        "id": f"{rec.project}:{rec.job_id}",
        "jobReference": {"projectId": rec.project, "jobId": rec.job_id},
        "user_email": rec.user_email,  # snake_case kept for backward-compat with existing tests
        "userEmail": rec.user_email,
        "configuration": {"jobType": rec.job_type},
        "status": {"state": rec.state},
        "statistics": {
            "startTime": rec.start_time,
            "endTime": rec.end_time,
            "creationTime": rec.create_time,
            "totalBytesProcessed": str(rec.total_bytes_processed),
        },
    }
    if rec.job_type == "LOAD":
        body["configuration"]["load"] = rec.load_config or {}
        body["statistics"]["load"] = rec.load_stats or {}
    else:
        body["configuration"]["query"] = {"query": rec.sql}
        body["statistics"]["query"] = {
            "totalBytesProcessed": str(rec.total_bytes_processed),
            "statementType": rec.statement_type,
        }
    if rec.error_result is not None:
        body["status"]["errorResult"] = rec.error_result
        body["status"]["errors"] = rec.errors
    if rec.destination_table is not None and rec.job_type != "LOAD":
        body["configuration"]["query"]["destinationTable"] = {
            "projectId": rec.destination_table[0],
            "datasetId": rec.destination_table[1],
            "tableId": rec.destination_table[2],
        }
    return body
```

(For LOAD jobs the destinationTable lives inside `configuration.load.destinationTable` and is set by the LoadRunner when it builds the load_config; we don't duplicate it here.)

- [ ] **Step 5: Run new + existing tests**

Run: `python -m pytest tests/unit/services/bigquery/test_models_load.py tests/unit/services/bigquery/test_routes_jobs.py tests/unit/services/bigquery/test_models.py -v`
Expected: PASS.

Run the full bigquery suite:

Run: `python -m pytest tests/unit/services/bigquery/ -v`
Expected: PASS (all existing + new tests).

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/bigquery/models.py \
        src/gcp_local/services/bigquery/routes/jobs.py \
        tests/unit/services/bigquery/test_models_load.py
git commit -m "$(cat <<'EOF'
feat(bigquery): JobRecord LOAD-type fields + _job_to_api branching

Adds optional load_config / load_stats fields to JobRecord (defaulting
to None) so a LOAD job can carry its source-format / disposition config
and counters. _job_to_api now emits configuration.load + statistics.load
for LOAD jobs and configuration.query + statistics.query for QUERY/DML,
matching real BigQuery's response shape.

No public behavior change for QUERY/DML jobs — all existing tests pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: NDJSON + CSV schema autodetect

Goal: pure functions in `engine/autodetect.py` that infer a `list[FieldSchema]` from parsed NDJSON rows or parsed CSV rows. No I/O, no DuckDB. All inferred fields default to `NULLABLE` (or `REPEATED` for arrays).

**Files:**
- Create: `src/gcp_local/services/bigquery/engine/autodetect.py`
- Create: `tests/unit/services/bigquery/test_autodetect_ndjson.py`
- Create: `tests/unit/services/bigquery/test_autodetect_csv.py`

- [ ] **Step 1: Write the failing NDJSON test**

`tests/unit/services/bigquery/test_autodetect_ndjson.py`:

```python
"""NDJSON schema inference (spec §7.1)."""

import pytest

from gcp_local.services.bigquery.engine.autodetect import (
    AutodetectError,
    autodetect_ndjson,
)


def test_int_column() -> None:
    schema = autodetect_ndjson([{"id": 1}, {"id": 2}])
    assert [(f.name, f.type, f.mode) for f in schema] == [("id", "INT64", "NULLABLE")]


def test_int_widens_to_float() -> None:
    schema = autodetect_ndjson([{"x": 1}, {"x": 2.5}])
    assert schema[0].type == "FLOAT64"


def test_bool_column() -> None:
    schema = autodetect_ndjson([{"flag": True}, {"flag": False}])
    assert schema[0].type == "BOOL"


def test_string_column() -> None:
    schema = autodetect_ndjson([{"name": "alice"}, {"name": "bob"}])
    assert schema[0].type == "STRING"


def test_string_wins_over_int_when_mixed() -> None:
    schema = autodetect_ndjson([{"v": 1}, {"v": "two"}])
    assert schema[0].type == "STRING"


def test_repeated_string() -> None:
    schema = autodetect_ndjson([{"tags": ["a", "b"]}, {"tags": ["c"]}])
    assert (schema[0].type, schema[0].mode) == ("STRING", "REPEATED")


def test_record_nested() -> None:
    schema = autodetect_ndjson([{"addr": {"city": "NYC", "zip": 10001}}])
    f = schema[0]
    assert f.type == "RECORD"
    assert f.mode == "NULLABLE"
    assert f.fields is not None
    sub = sorted(f.fields, key=lambda x: x.name)
    assert (sub[0].name, sub[0].type) == ("city", "STRING")
    assert (sub[1].name, sub[1].type) == ("zip", "INT64")


def test_null_in_column_doesnt_force_string() -> None:
    schema = autodetect_ndjson([{"x": None}, {"x": 1}, {"x": None}])
    assert schema[0].type == "INT64"
    assert schema[0].mode == "NULLABLE"


def test_first_100_rows_only() -> None:
    rows = [{"x": 1}] * 100 + [{"x": "later-string"}]
    # Only first 100 should be sampled, so type stays INT64.
    schema = autodetect_ndjson(rows)
    assert schema[0].type == "INT64"


def test_empty_payload_raises() -> None:
    with pytest.raises(AutodetectError):
        autodetect_ndjson([])


def test_keys_appearing_only_in_later_rows_are_picked_up() -> None:
    schema = autodetect_ndjson([{"id": 1}, {"id": 2, "name": "alice"}])
    by_name = {f.name: f for f in schema}
    assert by_name["id"].type == "INT64"
    assert by_name["name"].type == "STRING"
```

- [ ] **Step 2: Write the failing CSV test**

`tests/unit/services/bigquery/test_autodetect_csv.py`:

```python
"""CSV schema inference (spec §7.2)."""

import pytest

from gcp_local.services.bigquery.engine.autodetect import (
    AutodetectError,
    autodetect_csv,
)


def test_with_header_int_column() -> None:
    rows = [["id", "name"], ["1", "alice"], ["2", "bob"]]
    schema = autodetect_csv(rows, has_header=True)
    by_name = {f.name: f for f in schema}
    assert by_name["id"].type == "INT64"
    assert by_name["name"].type == "STRING"


def test_with_header_float_inferred_when_dot_present() -> None:
    rows = [["x"], ["1"], ["2.5"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "FLOAT64"


def test_with_header_bool_column() -> None:
    rows = [["flag"], ["true"], ["FALSE"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "BOOL"


def test_with_header_date_column() -> None:
    rows = [["d"], ["2024-01-01"], ["2024-12-31"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "DATE"


def test_with_header_timestamp_column() -> None:
    rows = [["ts"], ["2024-01-01T00:00:00Z"], ["2024-12-31T23:59:59Z"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "TIMESTAMP"


def test_no_header_synthesizes_column_names() -> None:
    rows = [["1", "alice"], ["2", "bob"]]
    schema = autodetect_csv(rows, has_header=False)
    assert [f.name for f in schema] == ["string_field_0", "string_field_1"]
    assert schema[0].type == "INT64"
    assert schema[1].type == "STRING"


def test_empty_cells_dont_constrain_type() -> None:
    rows = [["x"], [""], ["1"], ["", ""], ["2"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "INT64"


def test_mixed_int_and_string_falls_back_to_string() -> None:
    rows = [["x"], ["1"], ["abc"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "STRING"


def test_empty_payload_raises() -> None:
    with pytest.raises(AutodetectError):
        autodetect_csv([], has_header=True)


def test_header_only_no_data_raises() -> None:
    with pytest.raises(AutodetectError):
        autodetect_csv([["a", "b"]], has_header=True)
```

- [ ] **Step 3: Run both tests to verify failure**

Run: `python -m pytest tests/unit/services/bigquery/test_autodetect_ndjson.py tests/unit/services/bigquery/test_autodetect_csv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gcp_local.services.bigquery.engine.autodetect'`

- [ ] **Step 4: Implement `engine/autodetect.py`**

`src/gcp_local/services/bigquery/engine/autodetect.py`:

```python
"""Schema inference for inline-payload load jobs (spec §7.1, §7.2).

Pure functions: take parsed rows in, return a list[FieldSchema] out.
No I/O, no DuckDB. Walked over up to ``_SAMPLE_LIMIT`` rows to keep
inference fast on large payloads (matches real BigQuery's ~100-row cap).
"""

import re
from typing import Any

from gcp_local.services.bigquery.models import FieldSchema

_SAMPLE_LIMIT = 100

_RE_INT = re.compile(r"^-?\d+$")
_RE_FLOAT = re.compile(r"^-?\d+\.\d+$")
_RE_BOOL = re.compile(r"^(true|false)$", re.IGNORECASE)
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


class AutodetectError(ValueError):
    """Raised when schema cannot be inferred (e.g. empty payload)."""


def autodetect_ndjson(rows: list[dict[str, Any]]) -> list[FieldSchema]:
    """Infer a BQ schema from up to the first 100 NDJSON-parsed objects."""
    if not rows:
        raise AutodetectError("Cannot autodetect schema from empty input")
    sample = rows[:_SAMPLE_LIMIT]
    # Preserve key insertion order: first row's keys first, then any new
    # keys discovered in later rows in the order they appear.
    column_order: list[str] = []
    seen: set[str] = set()
    for row in sample:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                column_order.append(key)
    return [_infer_column(name, [r.get(name) for r in sample]) for name in column_order]


def _infer_column(name: str, values: list[Any]) -> FieldSchema:
    non_null = [v for v in values if v is not None]
    if not non_null:
        # All-null column → default to STRING/NULLABLE (matches BQ behavior
        # of treating undecidable columns as nullable strings).
        return FieldSchema(name=name, type="STRING", mode="NULLABLE", fields=None)

    # REPEATED detection: any list-typed value forces REPEATED inference.
    if all(isinstance(v, list) for v in non_null):
        # Recurse on flattened element values.
        flat = [item for v in non_null for item in v]
        if not flat:
            return FieldSchema(name=name, type="STRING", mode="REPEATED", fields=None)
        elem = _infer_column(name, flat)
        return FieldSchema(name=name, type=elem.type, mode="REPEATED", fields=elem.fields)

    # RECORD detection: all values are dicts.
    if all(isinstance(v, dict) for v in non_null):
        sub_keys: list[str] = []
        sub_seen: set[str] = set()
        for v in non_null:
            for k in v.keys():
                if k not in sub_seen:
                    sub_seen.add(k)
                    sub_keys.append(k)
        sub_fields = [_infer_column(k, [d.get(k) for d in non_null]) for k in sub_keys]
        return FieldSchema(name=name, type="RECORD", mode="NULLABLE", fields=sub_fields)

    types = {type(v) for v in non_null}
    if types == {bool}:
        return FieldSchema(name=name, type="BOOL", mode="NULLABLE", fields=None)
    if types <= {int, bool} and types != {bool}:
        # bool subclasses int in Python; treat any int presence as INT64.
        return FieldSchema(name=name, type="INT64", mode="NULLABLE", fields=None)
    if types <= {int, float, bool} and float in types:
        return FieldSchema(name=name, type="FLOAT64", mode="NULLABLE", fields=None)
    # Anything mixed or string-typed → STRING.
    return FieldSchema(name=name, type="STRING", mode="NULLABLE", fields=None)


def autodetect_csv(rows: list[list[str]], *, has_header: bool) -> list[FieldSchema]:
    """Infer a BQ schema from up to 100 CSV data rows.

    ``rows`` is the full list of parsed rows. ``has_header=True`` treats
    rows[0] as the header (column names); ``has_header=False`` synthesizes
    column names ``string_field_0``, ``string_field_1``, ... and includes
    rows[0] as data.
    """
    if not rows:
        raise AutodetectError("Cannot autodetect schema from empty input")
    if has_header:
        header = rows[0]
        data = rows[1 : 1 + _SAMPLE_LIMIT]
        if not data:
            raise AutodetectError("Cannot autodetect schema from header-only CSV")
    else:
        if not rows[0]:
            raise AutodetectError("Cannot autodetect schema from empty CSV")
        header = [f"string_field_{i}" for i in range(len(rows[0]))]
        data = rows[: _SAMPLE_LIMIT]

    columns: list[FieldSchema] = []
    for col_idx, name in enumerate(header):
        cells = [row[col_idx] for row in data if col_idx < len(row)]
        columns.append(FieldSchema(name=name, type=_infer_csv_cell_type(cells), mode="NULLABLE", fields=None))
    return columns


def _infer_csv_cell_type(cells: list[str]) -> str:
    non_empty = [c for c in cells if c != ""]
    if not non_empty:
        return "STRING"
    if all(_RE_BOOL.match(c) for c in non_empty):
        return "BOOL"
    if all(_RE_INT.match(c) for c in non_empty):
        return "INT64"
    if all(_RE_INT.match(c) or _RE_FLOAT.match(c) for c in non_empty) and any(
        _RE_FLOAT.match(c) for c in non_empty
    ):
        return "FLOAT64"
    if all(_RE_DATE.match(c) for c in non_empty):
        return "DATE"
    if all(_RE_TIMESTAMP.match(c) for c in non_empty):
        return "TIMESTAMP"
    return "STRING"
```

- [ ] **Step 5: Run both autodetect test files**

Run: `python -m pytest tests/unit/services/bigquery/test_autodetect_ndjson.py tests/unit/services/bigquery/test_autodetect_csv.py -v`
Expected: PASS (all tests above).

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/bigquery/engine/autodetect.py \
        tests/unit/services/bigquery/test_autodetect_ndjson.py \
        tests/unit/services/bigquery/test_autodetect_csv.py
git commit -m "$(cat <<'EOF'
feat(bigquery): NDJSON + CSV schema autodetect for load jobs

Pure-function inference helpers in engine/autodetect.py:
- autodetect_ndjson: walks first 100 parsed objects, widens types
  (BOOL → INT64 → FLOAT64 → STRING), recurses into RECORD/REPEATED.
- autodetect_csv: per-column type sniff over up to 100 rows; supports
  has_header=True (row 0 = header) and has_header=False (synthesizes
  string_field_N column names).

Both raise AutodetectError on empty input. Used in the next task by
LoadRunner when configuration.load.autodetect=True.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `LoadRunner` — NDJSON path + dispositions + LOAD JobRecord

Goal: a `LoadRunner` class that takes parsed NDJSON bytes + a `LoadJobConfig`, resolves the schema (explicit / autodetect / existing-table), creates the table if needed, applies the write disposition, runs the batched INSERT, and returns a populated `LOAD` `JobRecord`. CSV support is added in the next task.

**Files:**
- Create: `src/gcp_local/services/bigquery/engine/loads.py`
- Create: `tests/unit/services/bigquery/test_loads_ndjson.py`
- Create: `tests/unit/services/bigquery/test_load_dispositions.py`

- [ ] **Step 1: Write the failing happy-path test**

`tests/unit/services/bigquery/test_loads_ndjson.py`:

```python
"""NDJSON load-job execution (spec §6.1, §9)."""

from collections.abc import AsyncIterator

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def runner() -> AsyncIterator[LoadRunner]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    # Pre-create dataset; the runner will create tables as needed.
    from gcp_local.services.bigquery.models import DatasetRecord

    await storage.create_dataset(
        DatasetRecord(
            project="p",
            dataset_id="d",
            create_time="0",
            last_modified_time="0",
            description=None,
            labels={},
            location="US",
            default_table_expiration_ms=None,
        )
    )
    yield LoadRunner(connection=conn, storage=storage)
    await conn.shutdown()


@pytest.mark.asyncio
async def test_ndjson_explicit_schema_create_if_needed(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "alice"}\n{"id": 2, "name": "bob"}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t1"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="j1", load_config=config, data=body)
    assert rec.job_type == "LOAD"
    assert rec.error_result is None
    assert rec.total_rows == 2
    assert rec.load_stats["outputRows"] == "2"
    assert rec.load_stats["inputFileBytes"] == str(len(body))
    # Verify rows were actually inserted.
    rows = await runner._conn.execute('SELECT count(*) FROM "p:d"."t1"')
    assert rows[0][0] == 2


@pytest.mark.asyncio
async def test_ndjson_autodetect_creates_table(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "alice"}\n{"id": 2, "name": "bob"}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_auto"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "autodetect": True,
    }
    rec = await runner.run_load(project="p", job_id="j2", load_config=config, data=body)
    assert rec.error_result is None
    table = await runner._storage.get_table("p", "d", "t_auto")
    by_name = {f.name: f.type for f in table.schema}
    assert by_name == {"id": "INT64", "name": "STRING"}


@pytest.mark.asyncio
async def test_ndjson_create_never_missing_table(runner: LoadRunner) -> None:
    body = b'{"id": 1}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_missing"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "createDisposition": "CREATE_NEVER",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="j3", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "notFound"


@pytest.mark.asyncio
async def test_ndjson_unsupported_source_format(runner: LoadRunner) -> None:
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_pq"},
        "sourceFormat": "PARQUET",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="j4", load_config=config, data=b"")
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "PARQUET" in rec.error_result["message"]


@pytest.mark.asyncio
async def test_ndjson_parse_error_aborts_job(runner: LoadRunner) -> None:
    body = b'{"id": 1}\n{this is not json}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_bad"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="j5", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "line 2" in rec.error_result["message"]


@pytest.mark.asyncio
async def test_ndjson_no_schema_no_autodetect_no_table_errors(runner: LoadRunner) -> None:
    body = b'{"id": 1}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_noschema"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
    }
    rec = await runner.run_load(project="p", job_id="j6", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "schema" in rec.error_result["message"].lower()
```

- [ ] **Step 2: Write the failing disposition matrix test**

`tests/unit/services/bigquery/test_load_dispositions.py`:

```python
"""Write/create-disposition matrix for load jobs (spec §8)."""

from collections.abc import AsyncIterator

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


SCHEMA_FIELDS = [{"name": "id", "type": "INT64"}]


async def _seed_table(storage: BigQueryStorage, table_id: str) -> None:
    await storage.create_table(
        TableRecord(
            project="p",
            dataset_id="d",
            table_id=table_id,
            schema=[FieldSchema(name="id", type="INT64", mode="NULLABLE", fields=None)],
            create_time="0",
            last_modified_time="0",
            description=None,
            labels={},
            time_partitioning=None,
            range_partitioning=None,
            clustering=None,
        )
    )


async def _row_count(conn, table_id: str) -> int:
    rows = await conn.execute(f'SELECT count(*) FROM "p:d"."{table_id}"')
    return int(rows[0][0])


async def _insert_one(conn, table_id: str, value: int) -> None:
    await conn.execute(f'INSERT INTO "p:d"."{table_id}" VALUES (?)', [value])


@pytest.fixture
async def runner() -> AsyncIterator[LoadRunner]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    await storage.create_dataset(
        DatasetRecord(
            project="p", dataset_id="d", create_time="0", last_modified_time="0",
            description=None, labels={}, location="US", default_table_expiration_ms=None,
        )
    )
    yield LoadRunner(connection=conn, storage=storage)
    await conn.shutdown()


@pytest.mark.asyncio
async def test_write_append_default(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_app")
    await _insert_one(runner._conn, "t_app", 99)
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_app"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_app", load_config=config, data=b'{"id": 1}\n{"id": 2}\n'
    )
    assert rec.error_result is None
    assert await _row_count(runner._conn, "t_app") == 3


@pytest.mark.asyncio
async def test_write_truncate(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_trunc")
    for v in (10, 20, 30):
        await _insert_one(runner._conn, "t_trunc", v)
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_trunc"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "writeDisposition": "WRITE_TRUNCATE",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_tr", load_config=config, data=b'{"id": 1}\n'
    )
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT id FROM "p:d"."t_trunc" ORDER BY id')
    assert [r[0] for r in rows] == [1]


@pytest.mark.asyncio
async def test_write_empty_against_non_empty_fails(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_we")
    await _insert_one(runner._conn, "t_we", 7)
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_we"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "writeDisposition": "WRITE_EMPTY",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_we", load_config=config, data=b'{"id": 1}\n'
    )
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "duplicate"
    # Original row remains.
    assert await _row_count(runner._conn, "t_we") == 1


@pytest.mark.asyncio
async def test_write_empty_against_empty_succeeds(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_we_ok")
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_we_ok"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "writeDisposition": "WRITE_EMPTY",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_we2", load_config=config, data=b'{"id": 1}\n'
    )
    assert rec.error_result is None
    assert await _row_count(runner._conn, "t_we_ok") == 1


@pytest.mark.asyncio
async def test_create_if_needed_uses_existing_table_schema(runner: LoadRunner) -> None:
    """No explicit schema, no autodetect, but the table exists → use it."""
    await _seed_table(runner._storage, "t_existing")
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_existing"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
    }
    rec = await runner.run_load(
        project="p", job_id="j_e", load_config=config, data=b'{"id": 5}\n'
    )
    assert rec.error_result is None
    assert await _row_count(runner._conn, "t_existing") == 1
```

- [ ] **Step 3: Run tests to verify failure**

Run: `python -m pytest tests/unit/services/bigquery/test_loads_ndjson.py tests/unit/services/bigquery/test_load_dispositions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gcp_local.services.bigquery.engine.loads'`

- [ ] **Step 4: Implement `engine/loads.py`**

`src/gcp_local/services/bigquery/engine/loads.py`:

```python
"""Load-job execution: parse → resolve schema → apply dispositions → INSERT.

Spec sections: §6 (source-format parsing), §7 (schema resolution),
§8 (dispositions), §9 (execution), §10 (job-model integration).
"""

import datetime as dt
import json
from typing import Any

from gcp_local.services.bigquery.engine.autodetect import (
    AutodetectError,
    autodetect_ndjson,
)
from gcp_local.services.bigquery.engine.coerce import row_to_values, validate_row
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.models import (
    FieldSchema,
    JobRecord,
    TableRecord,
)
from gcp_local.services.bigquery.names import duckdb_table_qualname
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    TableNotFound,
)
from gcp_local.services.bigquery.types import (
    UnsupportedType,
    parse_table_schema,
)

_SUPPORTED_SOURCE_FORMATS = {"NEWLINE_DELIMITED_JSON", "CSV"}


def _now_epoch_ms_str() -> str:
    return str(int(dt.datetime.now(tz=dt.UTC).timestamp() * 1000))


class LoadRunner:
    """Executes load jobs against the shared BigQuery DuckDB connection."""

    def __init__(self, connection: BigQueryConnection, storage: BigQueryStorage) -> None:
        self._conn = connection
        self._storage = storage

    async def run_load(
        self,
        *,
        project: str,
        job_id: str,
        load_config: dict[str, Any],
        data: bytes,
    ) -> JobRecord:
        start = _now_epoch_ms_str()
        try:
            dest = _require_destination(load_config)
            source_format = (load_config.get("sourceFormat") or "").upper()
            if source_format not in _SUPPORTED_SOURCE_FORMATS:
                return self._fail(
                    project, job_id, load_config, start,
                    "invalid",
                    f"Unsupported sourceFormat: {source_format!r}",
                )
            rows = await self._parse_data(source_format, data, load_config)
            schema = await self._resolve_schema(load_config, dest, rows, source_format)
            await self._ensure_table(dest, schema, load_config)
            await self._apply_write_disposition(dest, load_config)
            inserted = await self._insert_rows(dest, schema, rows)
            return self._success(
                project=project,
                job_id=job_id,
                load_config=load_config,
                start=start,
                dest=dest,
                input_bytes=len(data),
                output_rows=inserted,
            )
        except _LoadError as e:
            return self._fail(project, job_id, load_config, start, e.reason, str(e))
        except (TableNotFound,) as e:
            return self._fail(project, job_id, load_config, start, "notFound", str(e))
        except (AutodetectError, UnsupportedType, ValueError) as e:
            return self._fail(project, job_id, load_config, start, "invalid", str(e))
        except Exception as e:
            return self._fail(project, job_id, load_config, start, "internalError", str(e))

    # ------------------------------------------------------------------
    # Parsing

    async def _parse_data(
        self,
        source_format: str,
        data: bytes,
        load_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if source_format == "NEWLINE_DELIMITED_JSON":
            return _parse_ndjson(data)
        if source_format == "CSV":
            # CSV path is added in a later task.
            raise _LoadError("invalid", "CSV source format not yet implemented")
        raise _LoadError("invalid", f"Unsupported sourceFormat: {source_format!r}")

    # ------------------------------------------------------------------
    # Schema resolution

    async def _resolve_schema(
        self,
        load_config: dict[str, Any],
        dest: tuple[str, str, str],
        rows: list[dict[str, Any]],
        source_format: str,
    ) -> list[FieldSchema]:
        explicit = (load_config.get("schema") or {}).get("fields")
        if explicit:
            return parse_table_schema(explicit)
        if load_config.get("autodetect"):
            if source_format == "NEWLINE_DELIMITED_JSON":
                return autodetect_ndjson(rows)
            # CSV autodetect handled in a later task.
            raise _LoadError("invalid", "CSV autodetect not yet implemented")
        # Fall back to existing-table schema.
        try:
            existing = await self._storage.get_table(*dest)
            return existing.schema
        except TableNotFound:
            raise _LoadError(
                "invalid",
                "Load configuration must specify schema or autodetect",
            ) from None

    # ------------------------------------------------------------------
    # Table existence + create

    async def _ensure_table(
        self,
        dest: tuple[str, str, str],
        schema: list[FieldSchema],
        load_config: dict[str, Any],
    ) -> None:
        create_disp = (load_config.get("createDisposition") or "CREATE_IF_NEEDED").upper()
        try:
            await self._storage.get_table(*dest)
            return
        except TableNotFound:
            pass
        if create_disp == "CREATE_NEVER":
            raise _LoadError(
                "notFound",
                f"Not found: Table {dest[0]}:{dest[1]}.{dest[2]}",
            )
        # CREATE_IF_NEEDED: materialize the table now.
        now = _now_epoch_ms_str()
        rec = TableRecord(
            project=dest[0],
            dataset_id=dest[1],
            table_id=dest[2],
            schema=schema,
            create_time=now,
            last_modified_time=now,
            description=None,
            labels={},
            time_partitioning=None,
            range_partitioning=None,
            clustering=None,
        )
        await self._storage.create_table(rec)

    # ------------------------------------------------------------------
    # Write disposition

    async def _apply_write_disposition(
        self,
        dest: tuple[str, str, str],
        load_config: dict[str, Any],
    ) -> None:
        disp = (load_config.get("writeDisposition") or "WRITE_APPEND").upper()
        qualname = duckdb_table_qualname(*dest)
        if disp == "WRITE_APPEND":
            return
        if disp == "WRITE_TRUNCATE":
            await self._conn.execute(f"DELETE FROM {qualname}")
            return
        if disp == "WRITE_EMPTY":
            rows = await self._conn.execute(f"SELECT 1 FROM {qualname} LIMIT 1")
            if rows:
                raise _LoadError(
                    "duplicate",
                    f"Already Exists: Table {dest[0]}:{dest[1]}.{dest[2]} is not empty",
                )
            return
        raise _LoadError("invalid", f"Unknown writeDisposition: {disp!r}")

    # ------------------------------------------------------------------
    # Insert

    async def _insert_rows(
        self,
        dest: tuple[str, str, str],
        schema: list[FieldSchema],
        rows: list[dict[str, Any]],
    ) -> int:
        if not rows:
            return 0
        # Validate every row up front; load jobs are all-or-nothing.
        all_errors: list[str] = []
        for i, row in enumerate(rows):
            errs = validate_row(row, schema)
            for e in errs:
                all_errors.append(f"row {i}: {e}")
        if all_errors:
            head = all_errors[:5]
            raise _LoadError(
                "invalid",
                f"{len(all_errors)} row validation error(s); first: " + "; ".join(head),
            )
        qualname = duckdb_table_qualname(*dest)
        placeholders = ",".join(
            "(" + ",".join(["?"] * len(schema)) + ")" for _ in rows
        )
        params: list[Any] = [v for row in rows for v in row_to_values(row, schema)]
        await self._conn.execute(f"INSERT INTO {qualname} VALUES {placeholders}", params)
        return len(rows)

    # ------------------------------------------------------------------
    # Job record builders

    def _success(
        self,
        *,
        project: str,
        job_id: str,
        load_config: dict[str, Any],
        start: str,
        dest: tuple[str, str, str],
        input_bytes: int,
        output_rows: int,
    ) -> JobRecord:
        end = _now_epoch_ms_str()
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="LOAD",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type="",
            sql="",
            destination_table=dest,
            total_rows=output_rows,
            total_bytes_processed=0,
            error_result=None,
            errors=[],
            load_config=load_config,
            load_stats={
                "inputFiles": "1",
                "inputFileBytes": str(input_bytes),
                "outputRows": str(output_rows),
                "outputBytes": str(input_bytes),
                "badRecords": "0",
            },
        )

    def _fail(
        self,
        project: str,
        job_id: str,
        load_config: dict[str, Any],
        start: str,
        reason: str,
        message: str,
    ) -> JobRecord:
        end = _now_epoch_ms_str()
        err = {"reason": reason, "message": message, "domain": "global"}
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="LOAD",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type="",
            sql="",
            destination_table=None,
            total_rows=0,
            total_bytes_processed=0,
            error_result=err,
            errors=[err],
            load_config=load_config,
            load_stats=None,
        )


# ----------------------------------------------------------------------
# Helpers


class _LoadError(Exception):
    """Raised internally to short-circuit run_load with a failed JobRecord."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _require_destination(load_config: dict[str, Any]) -> tuple[str, str, str]:
    dest = load_config.get("destinationTable") or {}
    project = dest.get("projectId")
    dataset_id = dest.get("datasetId")
    table_id = dest.get("tableId")
    if not (project and dataset_id and table_id):
        raise _LoadError(
            "invalid",
            "Load configuration must include destinationTable.{projectId,datasetId,tableId}",
        )
    return project, dataset_id, table_id


def _parse_ndjson(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8")
    rows: list[dict[str, Any]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise _LoadError("invalid", f"Failed to parse JSON: line {i}: {e}") from e
        if not isinstance(obj, dict):
            raise _LoadError(
                "invalid",
                f"NDJSON line {i} must be a JSON object, got {type(obj).__name__}",
            )
        rows.append(obj)
    return rows
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/unit/services/bigquery/test_loads_ndjson.py tests/unit/services/bigquery/test_load_dispositions.py -v`
Expected: PASS (all 11 cases above).

Run the full bigquery suite to confirm nothing broke:

Run: `python -m pytest tests/unit/services/bigquery/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/bigquery/engine/loads.py \
        tests/unit/services/bigquery/test_loads_ndjson.py \
        tests/unit/services/bigquery/test_load_dispositions.py
git commit -m "$(cat <<'EOF'
feat(bigquery): LoadRunner for inline NDJSON load jobs

engine/loads.py adds LoadRunner.run_load() — the orchestrator that:
- parses NDJSON line-by-line into row dicts
- resolves the schema (explicit → autodetect → existing-table → error)
- enforces createDisposition (CREATE_IF_NEEDED creates the table from
  the resolved schema; CREATE_NEVER fails with reason=notFound)
- applies writeDisposition (WRITE_APPEND default, WRITE_TRUNCATE deletes
  first, WRITE_EMPTY fails with reason=duplicate on non-empty target)
- validates every row against the schema and runs a single batched INSERT
- returns a populated LOAD JobRecord with load_stats populated

CSV source-format support is added in the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: CSV source-format support in `LoadRunner`

Goal: extend `LoadRunner._parse_data` and `_resolve_schema` to handle `sourceFormat=CSV`, including dialect parameters (`fieldDelimiter`, `quote`, `nullMarker`, `skipLeadingRows`, `encoding`) and CSV autodetect.

**Files:**
- Modify: `src/gcp_local/services/bigquery/engine/loads.py`
- Create: `tests/unit/services/bigquery/test_loads_csv.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_loads_csv.py`:

```python
"""CSV load-job execution (spec §6.2, §7.2)."""

from collections.abc import AsyncIterator

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.models import DatasetRecord
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def runner() -> AsyncIterator[LoadRunner]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    await storage.create_dataset(
        DatasetRecord(
            project="p", dataset_id="d", create_time="0", last_modified_time="0",
            description=None, labels={}, location="US", default_table_expiration_ms=None,
        )
    )
    yield LoadRunner(connection=conn, storage=storage)
    await conn.shutdown()


@pytest.mark.asyncio
async def test_csv_explicit_schema_skip_header(runner: LoadRunner) -> None:
    body = b"id,name\n1,alice\n2,bob\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_csv"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc1", load_config=config, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2
    rows = await runner._conn.execute('SELECT id, name FROM "p:d"."t_csv" ORDER BY id')
    assert [(r[0], r[1]) for r in rows] == [(1, "alice"), (2, "bob")]


@pytest.mark.asyncio
async def test_csv_autodetect_with_header(runner: LoadRunner) -> None:
    body = b"id,name\n1,alice\n2,bob\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_csv_auto"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "autodetect": True,
    }
    rec = await runner.run_load(project="p", job_id="jc2", load_config=config, data=body)
    assert rec.error_result is None
    table = await runner._storage.get_table("p", "d", "t_csv_auto")
    by_name = {f.name: f.type for f in table.schema}
    assert by_name == {"id": "INT64", "name": "STRING"}


@pytest.mark.asyncio
async def test_csv_custom_delimiter(runner: LoadRunner) -> None:
    body = b"id|name\n1|alice\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_pipe"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "fieldDelimiter": "|",
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc3", load_config=config, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 1


@pytest.mark.asyncio
async def test_csv_null_marker(runner: LoadRunner) -> None:
    body = b"id,name\n1,\\N\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_null"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "nullMarker": "\\N",
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc4", load_config=config, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT id, name FROM "p:d"."t_null"')
    assert rows[0][1] is None


@pytest.mark.asyncio
async def test_csv_no_header_synthesizes_columns(runner: LoadRunner) -> None:
    body = b"1,alice\n2,bob\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_noh"},
        "sourceFormat": "CSV",
        "autodetect": True,
    }
    rec = await runner.run_load(project="p", job_id="jc5", load_config=config, data=body)
    assert rec.error_result is None
    table = await runner._storage.get_table("p", "d", "t_noh")
    assert [f.name for f in table.schema] == ["string_field_0", "string_field_1"]


@pytest.mark.asyncio
async def test_csv_unsupported_encoding(runner: LoadRunner) -> None:
    body = b"id\n1\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_enc"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "encoding": "UTF-32",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="jc6", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "encoding" in rec.error_result["message"].lower()


@pytest.mark.asyncio
async def test_csv_column_count_mismatch(runner: LoadRunner) -> None:
    body = b"id,name\n1,alice,extra\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_mismatch"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc7", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/unit/services/bigquery/test_loads_csv.py -v`
Expected: FAIL — most cases hit the placeholder `"CSV source format not yet implemented"`.

- [ ] **Step 3: Add the CSV path to `engine/loads.py`**

Edit `src/gcp_local/services/bigquery/engine/loads.py`. Add `import csv` and `import io` at the top:

```python
import csv
import datetime as dt
import io
import json
from typing import Any
```

Also add the autodetect_csv import:

```python
from gcp_local.services.bigquery.engine.autodetect import (
    AutodetectError,
    autodetect_csv,
    autodetect_ndjson,
)
```

Add the `_SUPPORTED_CSV_ENCODINGS` constant near `_SUPPORTED_SOURCE_FORMATS`:

```python
_SUPPORTED_CSV_ENCODINGS = {"UTF-8", "UTF8", "ISO-8859-1", "LATIN-1"}
```

Replace `_parse_data`:

```python
    async def _parse_data(
        self,
        source_format: str,
        data: bytes,
        load_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if source_format == "NEWLINE_DELIMITED_JSON":
            return _parse_ndjson(data)
        if source_format == "CSV":
            csv_rows, header = _parse_csv(data, load_config)
            self._csv_cache = (csv_rows, header)  # cached for autodetect path
            # We can't materialize dict-rows yet because column names depend on
            # the resolved schema. Return an empty list and let _materialize_csv
            # produce dicts after schema resolution.
            return []
        raise _LoadError("invalid", f"Unsupported sourceFormat: {source_format!r}")
```

Hmm — but `run_load` calls `_resolve_schema(... rows)` which then calls `autodetect_ndjson(rows)`. The CSV path needs different state plumbing. Replace the simple straight-line `run_load` with a per-format split. Replace the `run_load` method body with:

```python
    async def run_load(
        self,
        *,
        project: str,
        job_id: str,
        load_config: dict[str, Any],
        data: bytes,
    ) -> JobRecord:
        start = _now_epoch_ms_str()
        try:
            dest = _require_destination(load_config)
            source_format = (load_config.get("sourceFormat") or "").upper()
            if source_format not in _SUPPORTED_SOURCE_FORMATS:
                return self._fail(
                    project, job_id, load_config, start,
                    "invalid",
                    f"Unsupported sourceFormat: {source_format!r}",
                )
            if source_format == "NEWLINE_DELIMITED_JSON":
                rows = _parse_ndjson(data)
                schema = await self._resolve_schema_ndjson(load_config, dest, rows)
            else:  # CSV
                csv_rows, has_header = _parse_csv(data, load_config)
                schema = await self._resolve_schema_csv(load_config, dest, csv_rows, has_header)
                rows = _csv_to_dict_rows(csv_rows, has_header, schema)
            await self._ensure_table(dest, schema, load_config)
            await self._apply_write_disposition(dest, load_config)
            inserted = await self._insert_rows(dest, schema, rows)
            return self._success(
                project=project,
                job_id=job_id,
                load_config=load_config,
                start=start,
                dest=dest,
                input_bytes=len(data),
                output_rows=inserted,
            )
        except _LoadError as e:
            return self._fail(project, job_id, load_config, start, e.reason, str(e))
        except (TableNotFound,) as e:
            return self._fail(project, job_id, load_config, start, "notFound", str(e))
        except (AutodetectError, UnsupportedType, ValueError) as e:
            return self._fail(project, job_id, load_config, start, "invalid", str(e))
        except Exception as e:
            return self._fail(project, job_id, load_config, start, "internalError", str(e))
```

Replace `_resolve_schema` with two helpers:

```python
    async def _resolve_schema_ndjson(
        self,
        load_config: dict[str, Any],
        dest: tuple[str, str, str],
        rows: list[dict[str, Any]],
    ) -> list[FieldSchema]:
        explicit = (load_config.get("schema") or {}).get("fields")
        if explicit:
            return parse_table_schema(explicit)
        if load_config.get("autodetect"):
            return autodetect_ndjson(rows)
        try:
            return (await self._storage.get_table(*dest)).schema
        except TableNotFound:
            raise _LoadError(
                "invalid",
                "Load configuration must specify schema or autodetect",
            ) from None

    async def _resolve_schema_csv(
        self,
        load_config: dict[str, Any],
        dest: tuple[str, str, str],
        csv_rows: list[list[str]],
        has_header: bool,
    ) -> list[FieldSchema]:
        explicit = (load_config.get("schema") or {}).get("fields")
        if explicit:
            return parse_table_schema(explicit)
        if load_config.get("autodetect"):
            return autodetect_csv(csv_rows, has_header=has_header)
        try:
            return (await self._storage.get_table(*dest)).schema
        except TableNotFound:
            raise _LoadError(
                "invalid",
                "Load configuration must specify schema or autodetect",
            ) from None
```

Add the CSV helpers at the bottom of the file (alongside `_parse_ndjson`):

```python
def _parse_csv(
    data: bytes,
    load_config: dict[str, Any],
) -> tuple[list[list[str]], bool]:
    encoding = (load_config.get("encoding") or "UTF-8").upper().replace("_", "-")
    if encoding not in _SUPPORTED_CSV_ENCODINGS:
        raise _LoadError("invalid", f"Unsupported CSV encoding: {encoding!r}")
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as e:
        raise _LoadError("invalid", f"CSV decode failed: {e}") from e
    delimiter = load_config.get("fieldDelimiter") or ","
    quotechar = load_config.get("quote") or '"'
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar=quotechar)
    rows = [r for r in reader if r]
    skip = int(load_config.get("skipLeadingRows") or 0)
    has_header = skip >= 1
    if has_header and skip > 1:
        # BQ semantics: skip N rows total; row 0 is header only when skip==1.
        # When skip>1, drop those rows entirely (they are pre-header garbage)
        # and continue treating row N as header.
        rows = rows[skip - 1:]
    null_marker = load_config.get("nullMarker") or ""
    # Cache the null marker on the resulting rows by replacing matching cells
    # with a sentinel that _csv_to_dict_rows turns into None.
    if null_marker:
        rows = [
            [_NULL_SENTINEL if c == null_marker else c for c in r]
            for r in rows
        ]
    return rows, has_header


_NULL_SENTINEL = object()


def _csv_to_dict_rows(
    csv_rows: list[list[str]],
    has_header: bool,
    schema: list[FieldSchema],
) -> list[dict[str, Any]]:
    if has_header:
        # Header row supplies column names but is not a data row.
        # Schema column order is the source of truth for ordering — we map
        # CSV cells positionally based on the header, then re-key by schema name.
        header = csv_rows[0]
        data = csv_rows[1:]
    else:
        header = [f.name for f in schema]
        data = csv_rows

    out: list[dict[str, Any]] = []
    for row_idx, row in enumerate(data):
        if len(row) != len(header):
            raise _LoadError(
                "invalid",
                f"CSV row {row_idx} has {len(row)} columns, expected {len(header)}",
            )
        payload: dict[str, Any] = {}
        for col_idx, cell in enumerate(row):
            name = header[col_idx]
            if cell is _NULL_SENTINEL:
                payload[name] = None
            else:
                payload[name] = _coerce_csv_cell(cell, name, schema)
        out.append(payload)
    return out


def _coerce_csv_cell(cell: str, name: str, schema: list[FieldSchema]) -> Any:
    by_name = {f.name: f for f in schema}
    field = by_name.get(name)
    if field is None:
        return cell
    if cell == "" and field.mode != "REQUIRED":
        return None
    match field.type:
        case "INT64" | "INTEGER":
            return int(cell)
        case "FLOAT64" | "FLOAT" | "NUMERIC" | "BIGNUMERIC":
            return float(cell)
        case "BOOL" | "BOOLEAN":
            return cell.strip().lower() == "true"
        case _:
            return cell
```

- [ ] **Step 4: Run CSV tests**

Run: `python -m pytest tests/unit/services/bigquery/test_loads_csv.py -v`
Expected: PASS (7 cases).

Run all bigquery unit tests:

Run: `python -m pytest tests/unit/services/bigquery/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/bigquery/engine/loads.py \
        tests/unit/services/bigquery/test_loads_csv.py
git commit -m "$(cat <<'EOF'
feat(bigquery): CSV source format in LoadRunner

Adds CSV parsing and dict-row materialization so load jobs accept
configuration.load.sourceFormat=CSV alongside NEWLINE_DELIMITED_JSON.

Supported dialect parameters:
- fieldDelimiter (default ',')
- quote (default '"')
- skipLeadingRows (default 0; >=1 treats row 0 as header)
- nullMarker (default ''; any cell matching becomes NULL)
- encoding (UTF-8 and ISO-8859-1; others fail with reason=invalid)

CSV schema autodetect uses the same per-column type sniffer (INT/FLOAT/
BOOL/DATE/TIMESTAMP/STRING) as the unit tests in autodetect_csv.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Multipart upload route

Goal: a new FastAPI router at `/upload/bigquery/v2/projects/{project}/jobs?uploadType=multipart` that parses `multipart/related` bodies, hands the data part to `LoadRunner`, and returns the resulting `Job` resource. Also wire `LoadRunner` construction into `service.py` and `app.py`.

**Files:**
- Create: `src/gcp_local/services/bigquery/routes/uploads.py`
- Create: `tests/unit/services/bigquery/test_routes_uploads_multipart.py`
- Modify: `src/gcp_local/services/bigquery/app.py`
- Modify: `src/gcp_local/services/bigquery/service.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_routes_uploads_multipart.py`:

```python
"""Multipart upload handler (spec §3, §5.1)."""

from collections.abc import AsyncIterator

import json
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> AsyncIterator[TestClient]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    load_runner = LoadRunner(connection=conn, storage=storage)
    app = build_app(storage=storage, runner=runner, load_runner=load_runner)
    try:
        c = TestClient(app)
        c.post(
            "/bigquery/v2/projects/p/datasets",
            json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
        )
        yield c
    finally:
        await conn.shutdown()


def _multipart_body(
    metadata: dict, data: bytes, *, data_type: str = "application/octet-stream"
) -> tuple[bytes, str]:
    boundary = "===gcp_local_test_boundary==="
    md_bytes = json.dumps(metadata).encode("utf-8")
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + md_bytes + b"\r\n" + (
        f"--{boundary}\r\nContent-Type: {data_type}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    content_type = f"multipart/related; boundary={boundary}"
    return body, content_type


def test_multipart_load_table_from_json_happy_path(client: TestClient) -> None:
    metadata = {
        "jobReference": {"projectId": "p", "jobId": "load-1"},
        "configuration": {
            "load": {
                "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "u1"},
                "sourceFormat": "NEWLINE_DELIMITED_JSON",
                "schema": {
                    "fields": [
                        {"name": "id", "type": "INT64"},
                        {"name": "name", "type": "STRING"},
                    ]
                },
            }
        },
    }
    data = b'{"id": 1, "name": "alice"}\n{"id": 2, "name": "bob"}\n'
    body, content_type = _multipart_body(metadata, data)
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": content_type},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["jobReference"]["jobId"] == "load-1"
    assert job["configuration"]["jobType"] == "LOAD"
    assert job["statistics"]["load"]["outputRows"] == "2"
    # Job is queryable via jobs.get afterward.
    g = client.get("/bigquery/v2/projects/p/jobs/load-1")
    assert g.status_code == 200
    assert g.json()["jobReference"]["jobId"] == "load-1"


def test_multipart_unsupported_uploadtype(client: TestClient) -> None:
    body, ct = _multipart_body({}, b"")
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "media"},
        content=body,
        headers={"Content-Type": ct},
    )
    assert r.status_code == 400
    assert r.json()["error"]["errors"][0]["reason"] == "invalid"


def test_multipart_malformed_no_metadata_part(client: TestClient) -> None:
    boundary = "==b=="
    body = (
        f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n"
        f"raw\r\n--{boundary}--\r\n"
    ).encode()
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    assert r.status_code == 400


def test_multipart_load_failure_surfaces_as_job_with_errorResult(
    client: TestClient,
) -> None:
    metadata = {
        "jobReference": {"projectId": "p", "jobId": "load-bad"},
        "configuration": {
            "load": {
                "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "u_bad"},
                "sourceFormat": "PARQUET",
                "schema": {"fields": [{"name": "id", "type": "INT64"}]},
            }
        },
    }
    body, ct = _multipart_body(metadata, b"")
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": ct},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["status"]["errorResult"]["reason"] == "invalid"
    assert "PARQUET" in job["status"]["errorResult"]["message"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/unit/services/bigquery/test_routes_uploads_multipart.py -v`
Expected: FAIL — `build_app` doesn't accept `load_runner`; uploads router doesn't exist.

- [ ] **Step 3: Implement `routes/uploads.py`**

`src/gcp_local/services/bigquery/routes/uploads.py`:

```python
"""Upload handlers: /upload/bigquery/v2/projects/{p}/jobs (spec §3).

Two upload styles share the endpoint, dispatched on uploadType:

- multipart: single POST with a multipart/related body (metadata JSON +
  data payload). Runs the load synchronously and returns the Job.
- resumable: init POST returns a session URL; PUT chunks accumulate into
  an in-memory buffer; the final PUT runs the load. (Added in next task.)
"""

import email
import email.policy
import json
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.errors import bigquery_error_response
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_project_id,
)


class MultipartParseError(ValueError):
    pass


def _envelope(status_code: int, message: str, reason: str = "invalid") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": status_code,
                "message": message,
                "errors": [{"reason": reason, "message": message, "domain": "global"}],
                "status": "INVALID_ARGUMENT" if reason == "invalid" else reason.upper(),
            }
        },
    )


def parse_multipart_related(body: bytes, content_type: str) -> tuple[dict[str, Any], bytes]:
    """Return (metadata_json, data_bytes) from a multipart/related body."""
    if "multipart/related" not in content_type.lower():
        raise MultipartParseError(
            f"expected multipart/related, got {content_type!r}"
        )
    # email.parser needs the Content-Type header on the message stream.
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    parts = [p for p in msg.iter_parts()]  # type: ignore[attr-defined]
    if len(parts) < 2:
        raise MultipartParseError(
            f"multipart body must have at least 2 parts, got {len(parts)}"
        )
    metadata_part = parts[0]
    data_part = parts[1]
    md_ct = metadata_part.get_content_type()
    if md_ct != "application/json":
        raise MultipartParseError(
            f"first part must be application/json, got {md_ct!r}"
        )
    try:
        metadata = json.loads(metadata_part.get_payload(decode=True).decode("utf-8"))
    except json.JSONDecodeError as e:
        raise MultipartParseError(f"metadata is not valid JSON: {e}") from e
    data = data_part.get_payload(decode=True) or b""
    return metadata, data


def build_router(
    runner: JobRunner,
    load_runner: LoadRunner,
) -> APIRouter:
    router = APIRouter(prefix="/upload/bigquery/v2/projects")

    @router.post("/{project}/jobs")
    async def upload_job(
        project: str,
        request: Request,
        uploadType: str = "",  # noqa: N803 — query param name matches BQ API
        content_type: str = Header(default="application/octet-stream"),
    ) -> Any:
        try:
            validate_project_id(project)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

        if uploadType == "multipart":
            return await _handle_multipart(
                project=project,
                body=await request.body(),
                content_type=content_type,
                load_runner=load_runner,
                runner=runner,
            )
        if uploadType == "resumable":
            # Resumable handler added in the next task — placeholder for now.
            return _envelope(400, "resumable uploads not yet implemented")
        return _envelope(400, f"Unsupported uploadType: {uploadType!r}")

    return router


async def _handle_multipart(
    *,
    project: str,
    body: bytes,
    content_type: str,
    load_runner: LoadRunner,
    runner: JobRunner,
) -> Any:
    try:
        metadata, data = parse_multipart_related(body, content_type)
    except MultipartParseError as e:
        return _envelope(400, str(e))
    return await _run_load_and_persist(
        project=project,
        metadata=metadata,
        data=data,
        load_runner=load_runner,
        runner=runner,
    )


async def _run_load_and_persist(
    *,
    project: str,
    metadata: dict[str, Any],
    data: bytes,
    load_runner: LoadRunner,
    runner: JobRunner,
) -> Any:
    job_ref = metadata.get("jobReference") or {}
    job_id = job_ref.get("jobId") or _gen_job_id()
    load_config = ((metadata.get("configuration") or {}).get("load")) or {}
    rec = await load_runner.run_load(
        project=project,
        job_id=job_id,
        load_config=load_config,
        data=data,
    )
    runner.register_external(rec)  # added in service.py wiring (Task 6 step 5)
    from gcp_local.services.bigquery.routes.jobs import _job_to_api

    return _job_to_api(rec)


def _gen_job_id() -> str:
    import uuid

    return f"job_{uuid.uuid4().hex}"
```

- [ ] **Step 4: Add `JobRunner.register_external` so LOAD jobs surface in `jobs.get` / `jobs.list`**

Edit `src/gcp_local/services/bigquery/engine/jobs.py`. Add this method to the `JobRunner` class (place it just below `cancel`):

```python
    def register_external(self, rec: JobRecord) -> None:
        """Persist a job that was executed by another runner (e.g. LoadRunner)."""
        self._jobs[(rec.project, rec.job_id)] = rec
        self._job_ended_at[(rec.project, rec.job_id)] = self._clock()
```

- [ ] **Step 5: Wire the uploads router in `app.py`**

Replace `src/gcp_local/services/bigquery/app.py`:

```python
from fastapi import FastAPI

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.routes.datasets import (
    build_router as datasets_router,
)
from gcp_local.services.bigquery.routes.jobs import (
    build_router as jobs_router,
)
from gcp_local.services.bigquery.routes.tabledata import (
    build_router as tabledata_router,
)
from gcp_local.services.bigquery.routes.tables import (
    build_router as tables_router,
)
from gcp_local.services.bigquery.routes.uploads import (
    build_router as uploads_router,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


def build_app(
    storage: BigQueryStorage,
    runner: JobRunner,
    load_runner: LoadRunner,
) -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    app.include_router(tables_router(storage))
    app.include_router(jobs_router(runner))
    app.include_router(tabledata_router(storage))
    app.include_router(uploads_router(runner, load_runner))
    return app
```

- [ ] **Step 6: Construct `LoadRunner` in `service.py`**

Edit `src/gcp_local/services/bigquery/service.py`. Add the import and field, and pass `load_runner` to `build_app`:

Add import near the existing engine imports:

```python
from gcp_local.services.bigquery.engine.loads import LoadRunner
```

Add a field to `__init__`:

```python
        self._load_runner: LoadRunner | None = None
```

In `start`, after constructing `self._runner`, add:

```python
        self._load_runner = LoadRunner(connection=self._connection, storage=self._storage)
```

And update the `build_app` call:

```python
        self._app = build_app(
            storage=self._storage,
            runner=self._runner,
            load_runner=self._load_runner,
        )
```

- [ ] **Step 7: Run multipart tests**

Run: `python -m pytest tests/unit/services/bigquery/test_routes_uploads_multipart.py -v`
Expected: PASS (4 cases).

Also run scaffold + tabledata + jobs route tests to confirm app wiring still works:

Run: `python -m pytest tests/unit/services/bigquery/ -v`
Expected: PASS — but note that `test_routes_tabledata.py::client` fixture and other route tests build `build_app(...)` directly and need to pass `load_runner=...`. Search for those call sites and update them.

Run:

```bash
grep -rn "build_app(" tests/ src/ 2>/dev/null
```

Update every test fixture that calls `build_app(storage=..., runner=...)` to also construct a `LoadRunner` and pass `load_runner=...`. Expected fixtures to update:

- `tests/unit/services/bigquery/test_routes_tabledata.py`
- `tests/unit/services/bigquery/test_routes_tables.py`
- `tests/unit/services/bigquery/test_routes_datasets.py`
- `tests/unit/services/bigquery/test_routes_jobs.py`
- `tests/unit/services/bigquery/test_service_scaffold.py` (if it calls `build_app`; likely uses the `BigQueryService` start path, in which case no change needed)

For each affected fixture, add:

```python
from gcp_local.services.bigquery.engine.loads import LoadRunner
# ...
load_runner = LoadRunner(connection=conn, storage=storage)
app = build_app(storage=storage, runner=runner, load_runner=load_runner)
```

- [ ] **Step 8: Re-run the full unit suite**

Run: `python -m pytest tests/unit/services/bigquery/ -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/gcp_local/services/bigquery/routes/uploads.py \
        src/gcp_local/services/bigquery/engine/jobs.py \
        src/gcp_local/services/bigquery/app.py \
        src/gcp_local/services/bigquery/service.py \
        tests/unit/services/bigquery/test_routes_uploads_multipart.py \
        tests/unit/services/bigquery/test_routes_tabledata.py \
        tests/unit/services/bigquery/test_routes_tables.py \
        tests/unit/services/bigquery/test_routes_datasets.py \
        tests/unit/services/bigquery/test_routes_jobs.py
git commit -m "$(cat <<'EOF'
feat(bigquery): multipart upload route for inline load jobs

POST /upload/bigquery/v2/projects/{p}/jobs?uploadType=multipart parses
multipart/related bodies via stdlib email.parser, hands the data part
plus configuration.load to LoadRunner, persists the resulting LOAD job
on JobRunner so it's visible to jobs.get/list, and returns the Job
resource. Resumable uploadType returns a placeholder 400 — added next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Resumable upload sessions

Goal: implement the resumable upload protocol — `POST?uploadType=resumable` to initiate, `PUT?upload_id=<sid>` to append chunks (308 while incomplete, 200 + Job on completion), `DELETE?upload_id=<sid>` to cancel. Sessions live in memory with a 10-minute TTL swept by the existing service-level sweeper.

**Files:**
- Create: `src/gcp_local/services/bigquery/engine/resumable.py`
- Create: `tests/unit/services/bigquery/test_resumable.py`
- Create: `tests/unit/services/bigquery/test_routes_uploads_resumable.py`
- Modify: `src/gcp_local/services/bigquery/routes/uploads.py`
- Modify: `src/gcp_local/services/bigquery/app.py`
- Modify: `src/gcp_local/services/bigquery/service.py`

- [ ] **Step 1: Write the failing session-store test**

`tests/unit/services/bigquery/test_resumable.py`:

```python
"""ResumableSessionStore unit tests (spec §5.2)."""

import pytest

from gcp_local.services.bigquery.engine.resumable import (
    OutOfOrderChunk,
    ResumableSessionNotFound,
    ResumableSessionStore,
)


def test_init_returns_session_id_and_stores_config() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={"sourceFormat": "CSV"}, declared_total=42)
    sess = store.get(sid)
    assert sess.project == "p"
    assert sess.declared_total == 42
    assert sess.received_total == 0


def test_append_completes_when_total_reached() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=10)
    store.append(sid, b"01234", start=0, end=4, total=10)
    assert store.get(sid).received_total == 5
    complete = store.append(sid, b"56789", start=5, end=9, total=10)
    assert complete is True


def test_append_returns_false_until_complete() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=10)
    assert store.append(sid, b"01234", start=0, end=4, total=10) is False


def test_append_out_of_order_raises() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=10)
    with pytest.raises(OutOfOrderChunk):
        store.append(sid, b"56789", start=5, end=9, total=10)


def test_unknown_session_raises() -> None:
    store = ResumableSessionStore()
    with pytest.raises(ResumableSessionNotFound):
        store.get("no-such-session")


def test_drop_removes_session() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=None)
    store.drop(sid)
    with pytest.raises(ResumableSessionNotFound):
        store.get(sid)


def test_total_unknown_streams_until_marked() -> None:
    """When client sends Content-Range bytes 0-9/* and later 10-19/20."""
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=None)
    assert store.append(sid, b"0123456789", start=0, end=9, total=None) is False
    assert store.append(sid, b"abcdefghij", start=10, end=19, total=20) is True


def test_sweep_expired_drops_old_sessions() -> None:
    store = ResumableSessionStore()
    clock = [100.0]
    store.set_clock(lambda: clock[0])
    sid_old = store.init(project="p", job_config={}, declared_total=None)
    clock[0] = 200.0
    sid_new = store.init(project="p", job_config={}, declared_total=None)
    clock[0] = 999.0  # 899s past sid_old's last_write, 799s past sid_new's
    store.sweep_expired(ttl_seconds=600)
    with pytest.raises(ResumableSessionNotFound):
        store.get(sid_old)
    # sid_new is still within TTL (last_write=200, now=999 → 799 > 600 → also expired).
    # Adjust: re-touch sid_new before sweep.
    clock[0] = 1000.0
    sid_fresh = store.init(project="p", job_config={}, declared_total=None)
    clock[0] = 1100.0  # 100s past sid_fresh's last_write
    store.sweep_expired(ttl_seconds=600)
    assert store.get(sid_fresh).received_total == 0
```

- [ ] **Step 2: Run failing test**

Run: `python -m pytest tests/unit/services/bigquery/test_resumable.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `engine/resumable.py`**

`src/gcp_local/services/bigquery/engine/resumable.py`:

```python
"""In-memory resumable-upload session store (spec §5.2)."""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ResumableSessionNotFound(KeyError):
    pass


class OutOfOrderChunk(ValueError):
    pass


@dataclass
class ResumableUpload:
    session_id: str
    project: str
    job_config: dict[str, Any]
    declared_total: int | None
    received_total: int = 0
    chunks: bytearray = field(default_factory=bytearray)
    last_write: float = 0.0


class ResumableSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ResumableUpload] = {}
        self._clock: Callable[[], float] = time.monotonic

    def set_clock(self, clock: Callable[[], float]) -> None:
        self._clock = clock

    def init(
        self,
        *,
        project: str,
        job_config: dict[str, Any],
        declared_total: int | None,
    ) -> str:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = ResumableUpload(
            session_id=session_id,
            project=project,
            job_config=job_config,
            declared_total=declared_total,
            last_write=self._clock(),
        )
        return session_id

    def get(self, session_id: str) -> ResumableUpload:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise ResumableSessionNotFound(session_id) from None

    def append(
        self,
        session_id: str,
        chunk: bytes,
        *,
        start: int,
        end: int,
        total: int | None,
    ) -> bool:
        """Append a chunk; return True if the upload is now complete."""
        sess = self.get(session_id)
        if start != sess.received_total:
            raise OutOfOrderChunk(
                f"expected start={sess.received_total}, got {start}"
            )
        sess.chunks.extend(chunk)
        sess.received_total = end + 1
        sess.last_write = self._clock()
        if total is not None:
            sess.declared_total = total
            return sess.received_total == total
        return False

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def sweep_expired(self, ttl_seconds: float) -> None:
        now = self._clock()
        expired = [
            sid
            for sid, sess in self._sessions.items()
            if (now - sess.last_write) > ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
```

- [ ] **Step 4: Run session-store tests**

Run: `python -m pytest tests/unit/services/bigquery/test_resumable.py -v`
Expected: PASS (8 cases).

- [ ] **Step 5: Write the failing route test**

`tests/unit/services/bigquery/test_routes_uploads_resumable.py`:

```python
"""Resumable upload route handler (spec §5.2)."""

from collections.abc import AsyncIterator

import json
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.engine.resumable import ResumableSessionStore
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> AsyncIterator[tuple[TestClient, ResumableSessionStore]]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    load_runner = LoadRunner(connection=conn, storage=storage)
    sessions = ResumableSessionStore()
    app = build_app(
        storage=storage, runner=runner, load_runner=load_runner, resumables=sessions,
    )
    try:
        c = TestClient(app)
        c.post(
            "/bigquery/v2/projects/p/datasets",
            json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
        )
        yield c, sessions
    finally:
        await conn.shutdown()


def _init_metadata(table: str = "rt") -> dict:
    return {
        "jobReference": {"projectId": "p", "jobId": f"load-{table}"},
        "configuration": {
            "load": {
                "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": table},
                "sourceFormat": "NEWLINE_DELIMITED_JSON",
                "schema": {"fields": [{"name": "id", "type": "INT64"}]},
            }
        },
    }


def test_resumable_init_returns_location(client) -> None:
    c, _ = client
    md = _init_metadata()
    r = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json", "X-Upload-Content-Length": "20"},
    )
    assert r.status_code == 200
    loc = r.headers.get("Location")
    assert loc is not None
    assert "upload_id=" in loc


def test_resumable_full_upload_completes(client) -> None:
    c, _ = client
    md = _init_metadata("rt2")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    payload = b'{"id": 1}\n{"id": 2}\n'
    r = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=payload,
        headers={"Content-Range": f"bytes 0-{len(payload) - 1}/{len(payload)}"},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["statistics"]["load"]["outputRows"] == "2"


def test_resumable_chunked_upload(client) -> None:
    c, _ = client
    md = _init_metadata("rt3")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    body = b'{"id": 1}\n{"id": 2}\n{"id": 3}\n'
    mid = len(body) // 2
    r1 = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=body[:mid],
        headers={"Content-Range": f"bytes 0-{mid - 1}/{len(body)}"},
    )
    assert r1.status_code == 308
    r2 = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=body[mid:],
        headers={"Content-Range": f"bytes {mid}-{len(body) - 1}/{len(body)}"},
    )
    assert r2.status_code == 200
    job = r2.json()
    assert job["statistics"]["load"]["outputRows"] == "3"


def test_resumable_unknown_session(client) -> None:
    c, _ = client
    r = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": "nope"},
        content=b"x",
        headers={"Content-Range": "bytes 0-0/1"},
    )
    assert r.status_code == 410
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


def test_resumable_out_of_order_chunk(client) -> None:
    c, _ = client
    md = _init_metadata("rt4")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    r = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=b"abc",
        headers={"Content-Range": "bytes 5-7/10"},
    )
    assert r.status_code == 400


def test_resumable_delete_drops_session(client) -> None:
    c, sessions = client
    md = _init_metadata("rt5")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    r = c.delete(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
    )
    assert r.status_code == 200
    # Subsequent PUT should now 410.
    r2 = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=b"x",
        headers={"Content-Range": "bytes 0-0/1"},
    )
    assert r2.status_code == 410
```

- [ ] **Step 6: Extend `routes/uploads.py` with the resumable handlers**

Edit `src/gcp_local/services/bigquery/routes/uploads.py`. Add imports and wire the store through:

Replace the imports block at the top with:

```python
import email
import email.policy
import json
import re
from typing import Any

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.engine.resumable import (
    OutOfOrderChunk,
    ResumableSessionNotFound,
    ResumableSessionStore,
)
from gcp_local.services.bigquery.errors import bigquery_error_response
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_project_id,
)


_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)
```

Replace `build_router` with:

```python
def build_router(
    runner: JobRunner,
    load_runner: LoadRunner,
    resumables: ResumableSessionStore,
) -> APIRouter:
    router = APIRouter(prefix="/upload/bigquery/v2/projects")

    @router.post("/{project}/jobs")
    async def upload_job(
        project: str,
        request: Request,
        uploadType: str = "",  # noqa: N803
        content_type: str = Header(default="application/octet-stream"),
    ) -> Any:
        try:
            validate_project_id(project)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

        body = await request.body()
        if uploadType == "multipart":
            return await _handle_multipart(
                project=project,
                body=body,
                content_type=content_type,
                load_runner=load_runner,
                runner=runner,
            )
        if uploadType == "resumable":
            return _handle_resumable_init(
                project=project,
                body=body,
                request=request,
                resumables=resumables,
            )
        return _envelope(400, f"Unsupported uploadType: {uploadType!r}")

    @router.put("/{project}/jobs")
    async def upload_chunk(
        project: str,
        request: Request,
        upload_id: str = "",  # noqa: N803
        content_range: str = Header(default=""),
    ) -> Any:
        try:
            validate_project_id(project)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()
        return await _handle_resumable_put(
            project=project,
            upload_id=upload_id,
            body=await request.body(),
            content_range=content_range,
            resumables=resumables,
            load_runner=load_runner,
            runner=runner,
        )

    @router.delete("/{project}/jobs")
    async def cancel_resumable(
        project: str,
        upload_id: str = "",  # noqa: N803
    ) -> Any:
        try:
            validate_project_id(project)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()
        resumables.drop(upload_id)
        return JSONResponse(status_code=200, content={})

    return router
```

Add the resumable helpers below `_run_load_and_persist`:

```python
def _handle_resumable_init(
    *,
    project: str,
    body: bytes,
    request: Request,
    resumables: ResumableSessionStore,
) -> Any:
    try:
        metadata = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        return _envelope(400, f"resumable init body is not valid JSON: {e}")
    load_config = ((metadata.get("configuration") or {}).get("load")) or {}
    declared_total_str = request.headers.get("X-Upload-Content-Length")
    declared_total = int(declared_total_str) if declared_total_str else None
    job_ref = metadata.get("jobReference") or {}
    # Stash the requested job_id on the session so the final PUT uses it.
    job_config = {"_metadata": metadata, "load": load_config}
    sid = resumables.init(
        project=project, job_config=job_config, declared_total=declared_total,
    )
    base = str(request.url).split("?")[0]
    location = f"{base}?upload_id={sid}"
    return Response(
        status_code=200,
        headers={"Location": location},
        content=b"",
    )


async def _handle_resumable_put(
    *,
    project: str,
    upload_id: str,
    body: bytes,
    content_range: str,
    resumables: ResumableSessionStore,
    load_runner: LoadRunner,
    runner: JobRunner,
) -> Any:
    if not upload_id:
        return _envelope(400, "missing upload_id")
    m = _CONTENT_RANGE_RE.match(content_range or "")
    if not m:
        return _envelope(400, f"invalid Content-Range: {content_range!r}")
    start = int(m.group(1))
    end = int(m.group(2))
    total_str = m.group(3)
    total = None if total_str == "*" else int(total_str)
    try:
        complete = resumables.append(upload_id, body, start=start, end=end, total=total)
    except ResumableSessionNotFound:
        return _envelope(410, f"resumable session not found: {upload_id}", reason="notFound")
    except OutOfOrderChunk as e:
        return _envelope(400, str(e))
    sess = resumables.get(upload_id)
    if not complete:
        return Response(
            status_code=308,
            headers={"Range": f"bytes=0-{sess.received_total - 1}"},
            content=b"",
        )
    metadata = sess.job_config["_metadata"]
    data = bytes(sess.chunks)
    resumables.drop(upload_id)
    return await _run_load_and_persist(
        project=project,
        metadata=metadata,
        data=data,
        load_runner=load_runner,
        runner=runner,
    )
```

- [ ] **Step 7: Update `app.py` and `service.py` to pass the resumable store**

Edit `src/gcp_local/services/bigquery/app.py`. Replace `build_app`:

```python
def build_app(
    storage: BigQueryStorage,
    runner: JobRunner,
    load_runner: LoadRunner,
    resumables: ResumableSessionStore | None = None,
) -> FastAPI:
    if resumables is None:
        resumables = ResumableSessionStore()
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    app.include_router(tables_router(storage))
    app.include_router(jobs_router(runner))
    app.include_router(tabledata_router(storage))
    app.include_router(uploads_router(runner, load_runner, resumables))
    return app
```

Add the import:

```python
from gcp_local.services.bigquery.engine.resumable import ResumableSessionStore
```

Edit `src/gcp_local/services/bigquery/service.py`. Add field, construction, and sweeper extension:

Add import:

```python
from gcp_local.services.bigquery.engine.resumable import ResumableSessionStore
```

Add field in `__init__`:

```python
        self._resumables: ResumableSessionStore | None = None
```

In `start`, after constructing `_load_runner`, add:

```python
        self._resumables = ResumableSessionStore()
```

Update the `build_app` call:

```python
        self._app = build_app(
            storage=self._storage,
            runner=self._runner,
            load_runner=self._load_runner,
            resumables=self._resumables,
        )
```

Replace the `_sweeper_loop` body:

```python
    async def _sweeper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(300)  # 5 minutes
                if self._runner is not None:
                    await self._runner.sweep_expired(ttl_seconds=3600)
                if self._resumables is not None:
                    self._resumables.sweep_expired(ttl_seconds=600)
        except asyncio.CancelledError:
            return
```

Update `reset_state` to also drop sessions:

```python
    async def reset_state(self) -> None:
        if self._connection is not None:
            await self._connection.reset()
        if self._resumables is not None:
            # Recreate to clear all sessions.
            self._resumables = ResumableSessionStore()
```

- [ ] **Step 8: Run resumable tests**

Run: `python -m pytest tests/unit/services/bigquery/test_routes_uploads_resumable.py tests/unit/services/bigquery/test_resumable.py -v`
Expected: PASS.

Run the full suite:

Run: `python -m pytest tests/unit/services/bigquery/ -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/gcp_local/services/bigquery/engine/resumable.py \
        src/gcp_local/services/bigquery/routes/uploads.py \
        src/gcp_local/services/bigquery/app.py \
        src/gcp_local/services/bigquery/service.py \
        tests/unit/services/bigquery/test_resumable.py \
        tests/unit/services/bigquery/test_routes_uploads_resumable.py
git commit -m "$(cat <<'EOF'
feat(bigquery): resumable uploads for inline load jobs

POST?uploadType=resumable initiates an in-memory session and returns
Location: <url>?upload_id=<sid>. PUT?upload_id=<sid> appends chunks
honoring Content-Range; intermediate chunks return 308, the final
chunk runs the load and returns 200 + Job. DELETE?upload_id=<sid>
drops the session. Out-of-order chunks → 400; unknown session → 410.

Sessions live in a ResumableSessionStore swept every 5 minutes
(piggybacks on the existing job-record sweeper) with a 10-minute TTL.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Integration tests with real `google-cloud-bigquery`

Goal: extend `tests/integration/test_bigquery_integration.py` with six new cases covering load jobs end-to-end via the official client. These prove that `client.load_table_from_json` and `client.load_table_from_file` work unchanged — including the auto-switch to resumable for large payloads.

**Files:**
- Modify: `tests/integration/test_bigquery_integration.py`

- [ ] **Step 1: Add the six load-job test cases**

Append the following block to `tests/integration/test_bigquery_integration.py` (after the existing tests):

```python
@pytest.mark.asyncio
async def test_load_table_from_json_explicit_schema(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_json")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "rows")
    schema = [
        SchemaField("id", "INT64", mode="REQUIRED"),
        SchemaField("name", "STRING"),
        SchemaField("payload", "JSON"),
    ]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    job_config = bigquery.LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON")
    rows = [
        {"id": i, "name": f"row-{i}", "payload": {"k": i}}
        for i in range(5)
    ]
    job = await _run(lambda: client.load_table_from_json(rows, table_ref, job_config=job_config))
    await _run(lambda: job.result())
    out = await _run(
        lambda: list(client.query(f"SELECT count(*) AS c FROM `test-project.ds_load_json.rows`").result())
    )
    assert out[0]["c"] == 5


@pytest.mark.asyncio
async def test_load_table_from_json_autodetect_creates_table(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_auto")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "auto_t")
    job_config = bigquery.LoadJobConfig(
        autodetect=True, source_format="NEWLINE_DELIMITED_JSON"
    )
    rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    job = await _run(lambda: client.load_table_from_json(rows, table_ref, job_config=job_config))
    await _run(lambda: job.result())
    table = await _run(lambda: client.get_table(table_ref))
    by_name = {f.name: f.field_type for f in table.schema}
    assert by_name == {"id": "INT64" if "INT64" in by_name.values() else "INTEGER", "name": "STRING"} or {
        "id": "INTEGER", "name": "STRING"
    } == by_name


@pytest.mark.asyncio
async def test_load_table_from_file_csv(emulator: dict[str, int]) -> None:
    import io

    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_csv")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "csv_t")
    schema = [SchemaField("id", "INT64"), SchemaField("name", "STRING")]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="CSV",
        skip_leading_rows=1,
    )
    csv_text = "id,name\n1,alice\n2,bob\n"
    job = await _run(
        lambda: client.load_table_from_file(
            io.BytesIO(csv_text.encode()),
            table_ref,
            job_config=job_config,
        )
    )
    await _run(lambda: job.result())
    rows = await _run(
        lambda: list(client.query("SELECT id, name FROM `test-project.ds_load_csv.csv_t` ORDER BY id").result())
    )
    assert [(r["id"], r["name"]) for r in rows] == [(1, "alice"), (2, "bob")]


@pytest.mark.asyncio
async def test_load_table_write_truncate(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_trunc")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "trunc_t")
    schema = [SchemaField("id", "INT64")]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    # Pre-populate via insertAll.
    await _run(lambda: client.insert_rows_json(table_ref, [{"id": 99}, {"id": 100}]))
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="NEWLINE_DELIMITED_JSON",
        write_disposition="WRITE_TRUNCATE",
    )
    job = await _run(
        lambda: client.load_table_from_json([{"id": 1}], table_ref, job_config=job_config)
    )
    await _run(lambda: job.result())
    rows = await _run(
        lambda: list(client.query("SELECT id FROM `test-project.ds_load_trunc.trunc_t`").result())
    )
    assert [r["id"] for r in rows] == [1]


@pytest.mark.asyncio
async def test_load_table_write_empty_against_non_empty_fails(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_we")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "we_t")
    schema = [SchemaField("id", "INT64")]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    await _run(lambda: client.insert_rows_json(table_ref, [{"id": 7}]))
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="NEWLINE_DELIMITED_JSON",
        write_disposition="WRITE_EMPTY",
    )
    with pytest.raises(gax_exceptions.GoogleAPICallError):
        job = await _run(
            lambda: client.load_table_from_json([{"id": 1}], table_ref, job_config=job_config)
        )
        await _run(lambda: job.result())


@pytest.mark.asyncio
async def test_load_table_resumable_large_payload(emulator: dict[str, int]) -> None:
    """Force the official client into resumable mode by sending ~6 MiB of NDJSON."""
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_big")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "big_t")
    schema = [SchemaField("id", "INT64"), SchemaField("blob", "STRING")]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    # ~6 MiB of NDJSON (each row ~250 B; 25_000 rows ≈ 6.2 MiB).
    big_blob = "x" * 240
    rows = [{"id": i, "blob": big_blob} for i in range(25_000)]
    job_config = bigquery.LoadJobConfig(
        schema=schema, source_format="NEWLINE_DELIMITED_JSON"
    )
    job = await _run(
        lambda: client.load_table_from_json(rows, table_ref, job_config=job_config)
    )
    await _run(lambda: job.result())
    count = await _run(
        lambda: list(client.query("SELECT count(*) AS c FROM `test-project.ds_load_big.big_t`").result())
    )
    assert count[0]["c"] == 25_000
```

- [ ] **Step 2: Run the full integration suite**

Run: `python -m pytest tests/integration/test_bigquery_integration.py -v`
Expected: PASS — all existing tests plus 6 new load-job cases.

- [ ] **Step 3: Run the entire test suite**

Run: `python -m pytest -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_bigquery_integration.py
git commit -m "$(cat <<'EOF'
test(bigquery): integration tests for inline load jobs

Six new cases driving real google-cloud-bigquery against the emulator:
- load_table_from_json with explicit schema
- load_table_from_json with autodetect=True creating the destination
- load_table_from_file with CSV + skip_leading_rows
- WRITE_TRUNCATE replaces existing rows
- WRITE_EMPTY against non-empty target raises GoogleAPICallError
- ~6 MiB load_table_from_json forces resumable upload path

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: User-facing docs + README update

Goal: add a "Load jobs" section to `docs/services/bigquery.md` with NDJSON and CSV examples, and update `README.md` to remove load jobs from the BigQuery "not emulated" list.

**Files:**
- Modify: `docs/services/bigquery.md`
- Modify: `README.md`

- [ ] **Step 1: Add the Load jobs section to `docs/services/bigquery.md`**

Insert this section in `docs/services/bigquery.md` between the "What's emulated" section's bullet list and the "What's not emulated (v1)" section. Also remove "Load jobs (`LoadJobConfiguration`)" from the "What's not emulated" list (replace it with `Load jobs sourcing from gs:// URIs (inline NDJSON + CSV uploads ARE supported — see "Load jobs" below)`).

Then add this section just before "## Connecting":

````markdown
---

## Load jobs

The emulator supports **inline-payload load jobs** — `client.load_table_from_json(...)` and `client.load_table_from_file(..., source_format=NEWLINE_DELIMITED_JSON | CSV)` work unchanged. GCS-URI loads (`source_uris=["gs://..."]`) and binary formats (Parquet, Avro, ORC) are not supported in v1.

### Inline NDJSON

```python
from google.cloud.bigquery import LoadJobConfig, SchemaField

schema = [
    SchemaField("id", "INT64", mode="REQUIRED"),
    SchemaField("name", "STRING"),
    SchemaField("payload", "JSON"),
]
job_config = LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON")
rows = [{"id": 1, "name": "alice", "payload": {"k": 1}}]
job = client.load_table_from_json(rows, table_ref, job_config=job_config)
job.result()  # blocks until done; load runs synchronously inside the emulator
```

### Inline CSV

```python
import io
from google.cloud.bigquery import LoadJobConfig, SchemaField

schema = [SchemaField("id", "INT64"), SchemaField("name", "STRING")]
job_config = LoadJobConfig(
    schema=schema,
    source_format="CSV",
    skip_leading_rows=1,
)
csv_text = "id,name\n1,alice\n2,bob\n"
job = client.load_table_from_file(io.BytesIO(csv_text.encode()), table_ref, job_config=job_config)
job.result()
```

### Schema autodetect

`LoadJobConfig(autodetect=True)` works for both NDJSON and CSV:

```python
job_config = LoadJobConfig(autodetect=True, source_format="NEWLINE_DELIMITED_JSON")
job = client.load_table_from_json(
    [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}],
    table_ref,
    job_config=job_config,
)
job.result()
# Table is created automatically with inferred schema (id INT64, name STRING).
```

For NDJSON, the emulator walks the first 100 rows and widens types per top-level key (`BOOL → INT64 → FLOAT64 → STRING`; nested objects → `RECORD`; arrays → `REPEATED`). For CSV, the emulator sniffs each column over up to 100 rows; without a header (`skip_leading_rows=0`), columns are named `string_field_0`, `string_field_1`, ...

### Write dispositions

| `write_disposition` | Behavior |
|---|---|
| `WRITE_APPEND` (default) | Rows are appended to the existing table. |
| `WRITE_TRUNCATE` | Existing rows are deleted before the load. |
| `WRITE_EMPTY` | Load fails if the table already contains rows (`reason: duplicate`). |

### Create dispositions

| `create_disposition` | Behavior |
|---|---|
| `CREATE_IF_NEEDED` (default) | The table is created from the resolved schema if it doesn't exist. |
| `CREATE_NEVER` | The job fails with `reason: notFound` if the table doesn't exist. |

### What about large payloads?

The official client automatically switches from a single multipart POST to a chunked resumable upload once the payload exceeds `_DEFAULT_CHUNKSIZE` (about 5 MiB). The emulator handles both — large `load_table_from_json` calls work with no extra configuration.
````

- [ ] **Step 2: Update `README.md`**

In `README.md`, the BigQuery row in the Services table doesn't need changes, but if the README has a feature summary mentioning "no load jobs", remove that constraint. Search:

```bash
grep -n -i "load job" README.md
```

If any hit refers to a missing feature, update the wording to "inline NDJSON + CSV load jobs supported; GCS-URI loads not yet implemented".

- [ ] **Step 3: Confirm the docs render plausibly**

Run: `python -m pytest tests/ -v`
Expected: PASS (no doc-driven tests; ensures no regressions).

Also visually inspect `docs/services/bigquery.md` to confirm the new section sits between the existing list and "Connecting".

- [ ] **Step 4: Commit**

```bash
git add docs/services/bigquery.md README.md
git commit -m "$(cat <<'EOF'
docs(bigquery): document inline NDJSON + CSV load jobs

Adds a "Load jobs" section to docs/services/bigquery.md with NDJSON,
CSV, autodetect, write/create disposition, and resumable-upload
guidance. Removes load jobs from the README's BigQuery "not emulated"
list (GCS-URI loads remain out of scope).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Open the pull request

Goal: push the branch and open a PR to `master`.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin bigquery-load-jobs
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base master --title "feat(bigquery): inline NDJSON + CSV load jobs" --body "$(cat <<'EOF'
## Summary

- Adds `/upload/bigquery/v2/projects/{p}/jobs` endpoints (multipart + resumable) so `client.load_table_from_json(...)` and `client.load_table_from_file(..., source_format=NEWLINE_DELIMITED_JSON | CSV)` work unchanged against the emulator.
- New `LoadRunner` shares the row-coercion path with `tabledata.insertAll` via the extracted `engine/coerce.py` helper module.
- Full `writeDisposition` (APPEND/TRUNCATE/EMPTY) and `createDisposition` (IF_NEEDED/NEVER) support; explicit schema and autodetect (NDJSON + CSV); new `LOAD` job type appearing in `jobs.get` / `jobs.list`.
- GCS-URI loads (`source_uris=["gs://..."]`) and binary formats (Parquet/Avro/ORC) remain out of scope.

## Test plan

- [ ] `python -m pytest tests/unit/services/bigquery/ -v` passes
- [ ] `python -m pytest tests/integration/test_bigquery_integration.py -v` passes (includes 6 new load-job cases driving real `google-cloud-bigquery`)
- [ ] `python -m pytest -v` passes the full suite
- [ ] Manual: `client.load_table_from_json` round-trip works end-to-end against a locally-built image

## References

- Spec: `docs/superpowers/specs/2026-04-26-gcp-local-bigquery-load-jobs-design.md`
- Plan: `docs/superpowers/plans/2026-04-26-gcp-local-bigquery-load-jobs.md`
EOF
)"
```

- [ ] **Step 3: Print the PR URL**

`gh pr create` prints the PR URL on success; capture it for the user.

---

## Self-review checklist (run after writing this plan)

This section is for the plan author to verify spec coverage before handing off.

- **Spec §2 (scope):** Tasks 4 (NDJSON), 5 (CSV), 6 (multipart), 7 (resumable), 8 (integration); GCS-URI loads + Parquet/Avro/ORC explicitly rejected in `LoadRunner._parse_data` (Task 4 Step 4 + test `test_ndjson_unsupported_source_format`). ✓
- **Spec §3 (URL surface):** Tasks 6 + 7 implement POST/PUT/DELETE on `/upload/bigquery/v2/projects/{p}/jobs`. ✓
- **Spec §4 (package layout):** All new/modified files enumerated above and in the File Structure section. ✓
- **Spec §5.1 (multipart parsing):** Task 6 Step 3 (`parse_multipart_related` via `email.parser`). ✓
- **Spec §5.2 (resumable):** Task 7 Step 3 (`ResumableSessionStore`) + Step 6 (handlers + 308/200/410 semantics + sweeper). ✓
- **Spec §6 (source-format parsing):** Tasks 4 (NDJSON) + 5 (CSV with dialect parameters). ✓
- **Spec §7 (schema resolution):** Task 3 (autodetect helpers) + Task 4 (`_resolve_schema_ndjson`) + Task 5 (`_resolve_schema_csv`). ✓
- **Spec §8 (dispositions):** Task 4 Step 4 (`_apply_write_disposition`, `_ensure_table`) + Task 4 disposition matrix tests. ✓
- **Spec §9 (execution):** Task 4 Step 4 (`_insert_rows`, `_success`, `load_stats` shape). ✓
- **Spec §10 (job model):** Task 2 (JobRecord extension + `_job_to_api` branching). ✓
- **Spec §11 (errors):** Task 4 (`_LoadError` with reasons), Task 6 (multipart envelope), Task 7 (resumable 410/400). ✓
- **Spec §12.1 (unit tests):** test_coerce, test_autodetect_*, test_loads_*, test_load_dispositions, test_resumable, test_routes_uploads_*. ✓
- **Spec §12.2 (integration tests):** 6 cases in Task 8. ✓
- **Spec §13 (admin):** Task 7 Step 7 updates `reset_state` to clear sessions. ✓
- **Spec §14 (deps):** No runtime deps added; Task 1 step 5 uses existing test infrastructure. ✓
- **Spec §15 (docs):** Task 9. ✓
- **Spec §16 (maestro-evals migration):** Out of scope of this PR per spec §16; not implemented in this plan. ✓ (intentional)
- **Spec §17 (`maxBadRecords` / `ignoreUnknownValues` / `encoding`):** `encoding` is honored in Task 5 (`_parse_csv` decode + allow-list). `maxBadRecords` and `ignoreUnknownValues` are NOT implemented in this plan — they are accepted-but-ignored by the current `_insert_rows` (which fails the whole job on any validation error). **Gap: should be added or explicitly documented as deferred.** Decision: add a brief follow-up note rather than expanding plan scope.

---
