# gcp-local BigQuery Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the BigQuery service so the official `google-cloud-bigquery` Python client library works unchanged against the emulator over REST. Covers dataset/table CRUD, query (sync + async-shaped), DML (INSERT/UPDATE/DELETE/MERGE), streaming inserts (`tabledata.insertAll`), and `INFORMATION_SCHEMA`. No load jobs, no copy/extract, no ML/geo/scripting (per spec §2 out-of-scope).

**Architecture:** New `gcp_local.services.bigquery` package registered as a Service. The service owns a FastAPI `uvicorn` listener on port 9050. SQL execution is delegated to an embedded DuckDB connection; incoming BigQuery SQL is parsed with `sqlglot`, run through a small set of AST passes (three-part-name rewrite, wildcard expansion, `SAFE.` rewrite, `INFORMATION_SCHEMA` resolution, partitioning DDL strip) and transpiled to DuckDB SQL. Catalog metadata (dataset/table records that DuckDB doesn't preserve — modes, partitioning config, labels) lives in a `_gcp_local_meta` schema inside the same DuckDB database. Query result rows are materialized into temp tables in a `_gcp_local_jobs` schema and paged via `LIMIT/OFFSET`.

**Tech Stack:** Python 3.13, FastAPI/uvicorn (REST), `duckdb` (query engine), `sqlglot` (BQ→DuckDB translation), `google-cloud-bigquery` (test-only driver), `db-dtypes` + `pyarrow` (test-only for `to_dataframe`/`to_arrow`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-25-gcp-local-bigquery-design.md`

**Branch:** `bigquery` (create at start of Task 1). All commits land on this branch; when all tasks pass, open a PR to `master`.

**Commit policy:** Commits allowed in this session. Use `python -m pip` (not bare `pip`). Do not bypass signing/hooks. Trailer on every commit (HEREDOC):
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## File structure

```
src/gcp_local/services/bigquery/
  __init__.py                              # exports BigQueryService
  service.py                               # BigQueryService (Service protocol impl)
  app.py                                   # FastAPI app factory + router wiring
  errors.py                                # exception types + REST envelope helper
  names.py                                 # resource-name parser/validator + DuckDB schema builder
  types.py                                 # BQ FieldSchema ↔ DuckDB DDL + row serializer
  models.py                                # DatasetRecord, TableRecord, FieldSchema, JobRecord
  storage.py                               # BigQueryStorage (datasets/tables CRUD over catalog)
  engine/
    __init__.py
    connection.py                          # DuckDB connection + catalog bootstrap
    translate.py                           # sqlglot BQ→DuckDB pipeline + AST passes
    shims.py                               # BQ-specific UDFs registered on the connection
    info_schema.py                         # AST rewrite for INFORMATION_SCHEMA references
    jobs.py                                # JobRunner: execute SQL, materialize results, page, TTL sweep
  routes/
    __init__.py
    datasets.py                            # /projects/{p}/datasets/* handlers
    tables.py                              # /projects/{p}/datasets/{d}/tables/* handlers
    jobs.py                                # /projects/{p}/jobs/* handlers + queries + getQueryResults
    tabledata.py                           # /projects/{p}/datasets/{d}/tables/{t}/insertAll

tests/unit/services/bigquery/
  __init__.py
  test_names.py
  test_types.py
  test_models.py
  test_connection.py
  test_storage.py
  test_translate.py
  test_shims.py
  test_info_schema.py
  test_jobs.py
  test_errors.py
  test_routes_datasets.py
  test_routes_tables.py
  test_routes_jobs.py
  test_routes_tabledata.py

tests/integration/
  test_bigquery_integration.py             # real google-cloud-bigquery driver
```

---

## Task 1: Runtime deps + service scaffold + entry-point registration

Goal: a `BigQueryService` that boots a FastAPI server on port 9050 with a single root health route. No domain logic yet. Wires the service into the registry via entry point so the existing `emulator` boot path picks it up.

**Files:**
- Modify: `pyproject.toml` (runtime deps, dev deps, entry point)
- Create: `src/gcp_local/services/bigquery/__init__.py`
- Create: `src/gcp_local/services/bigquery/service.py`
- Create: `src/gcp_local/services/bigquery/app.py`
- Create: `tests/unit/services/bigquery/__init__.py`
- Create: `tests/unit/services/bigquery/test_service_scaffold.py`

- [ ] **Step 1: Create branch**

```bash
git switch -c bigquery
```

- [ ] **Step 2: Write the failing test**

`tests/unit/services/bigquery/test_service_scaffold.py`:

```python
import asyncio
import socket
from pathlib import Path

import httpx
import pytest

from gcp_local.core.context import Context
from gcp_local.core.state_hub import StateHub
from gcp_local.services.bigquery import BigQueryService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_service_starts_and_serves_root(tmp_path: Path) -> None:
    port = _free_port()
    ctx = Context(
        persist=False,
        data_dir=tmp_path,
        port_overrides={"bigquery": port},
        state_hub=StateHub(),
    )
    svc = BigQueryService()
    await svc.start(ctx)
    try:
        # Wait for server to bind.
        for _ in range(50):
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"http://127.0.0.1:{port}/")
                if r.status_code == 200:
                    break
            except httpx.ConnectError:
                await asyncio.sleep(0.05)
        else:
            raise AssertionError("bigquery service did not start")
        assert r.json() == {"service": "bigquery", "status": "ok"}
        assert svc.health().ok is True
    finally:
        await svc.stop()
        assert svc.health().ok is False


def test_service_declares_default_port() -> None:
    svc = BigQueryService()
    assert svc.name == "bigquery"
    assert [p.number for p in svc.default_ports] == [9050]
    assert [p.protocol for p in svc.default_ports] == ["rest"]
```

- [ ] **Step 3: Run — fails**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_service_scaffold.py -v
```

Expected: `ImportError` on `gcp_local.services.bigquery`.

- [ ] **Step 4: Add deps and entry point in `pyproject.toml`**

Update `dependencies = [...]` to add:

```toml
    "duckdb>=0.10",
    "sqlglot>=23.0",
```

Update `[project.optional-dependencies].dev` to add:

```toml
    "db-dtypes>=1.2",
    "pyarrow>=15",
```

Update `[project.entry-points."gcp_local.services"]` to add:

```toml
bigquery = "gcp_local.services.bigquery:BigQueryService"
```

Reinstall:

```bash
. .venv/bin/activate && python -m pip install -e ".[dev]"
```

- [ ] **Step 5: Create `src/gcp_local/services/bigquery/__init__.py`**

```python
from gcp_local.services.bigquery.service import BigQueryService

__all__ = ["BigQueryService"]
```

- [ ] **Step 6: Create `src/gcp_local/services/bigquery/app.py`**

```python
from fastapi import FastAPI


def build_app() -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    return app
```

- [ ] **Step 7: Create `src/gcp_local/services/bigquery/service.py`**

```python
import asyncio
import logging
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.bigquery.app import build_app

log = logging.getLogger(__name__)

_DEFAULT_PORT = 9050


class BigQueryService:
    """Emulates Google BigQuery over a REST API."""

    name = "bigquery"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = build_app()
        self._server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(
            self._server.serve(), name=f"{self.name}-server"
        )
        self._started = True
        log.info("bigquery service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        self._started = False

    async def reset_state(self) -> None:
        # No state yet — added in Task 5.
        return

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self._started, message="running" if self._started else "stopped"
        )
```

- [ ] **Step 8: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_service_scaffold.py -v
```

All 2 PASS.

- [ ] **Step 9: Quality gate**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
```

All green. The full suite still passes (the new entry point loads without side effects).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml src/gcp_local/services/bigquery tests/unit/services/bigquery
git commit -m "$(cat <<'EOF'
feat(bigquery): service scaffold + register on port 9050

Adds the BigQuery service skeleton with a FastAPI listener and
registers it via the gcp_local.services entry-point group.
DuckDB/sqlglot pulled in as runtime deps; db-dtypes/pyarrow
pulled in as dev deps for upcoming integration tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Resource-name parser + DuckDB schema-name builder

Goal: a `names.py` module that parses BigQuery resource names (`projects/<p>/datasets/<d>`, `projects/<p>/datasets/<d>/tables/<t>`, three-part backtick names `` `p.d.t` ``), validates per spec §4.1 rules, and builds quoted DuckDB identifiers using the `:` separator from spec §5.1.

**Files:**
- Create: `src/gcp_local/services/bigquery/names.py`
- Create: `tests/unit/services/bigquery/test_names.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_names.py`:

```python
import pytest

from gcp_local.services.bigquery.names import (
    DatasetRef,
    InvalidName,
    JobRef,
    TableRef,
    duckdb_schema_name,
    duckdb_table_qualname,
    parse_dataset_path,
    parse_job_path,
    parse_table_path,
    parse_three_part,
    validate_dataset_id,
    validate_job_id,
    validate_project_id,
    validate_table_id,
)


# project IDs

def test_project_id_accepts_lowercase_alnum_dash() -> None:
    validate_project_id("my-project-1")


def test_project_id_rejects_uppercase() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("MyProject")


def test_project_id_rejects_underscore() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("my_project")


def test_project_id_rejects_colon() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("a:b")


def test_project_id_rejects_empty_or_too_long() -> None:
    with pytest.raises(InvalidName):
        validate_project_id("")
    with pytest.raises(InvalidName):
        validate_project_id("a" * 64)


# dataset IDs

def test_dataset_id_accepts_alnum_underscore() -> None:
    validate_dataset_id("My_Dataset_1")


def test_dataset_id_accepts_starting_with_digit() -> None:
    validate_dataset_id("1day")  # BQ allows this


def test_dataset_id_rejects_dash() -> None:
    with pytest.raises(InvalidName):
        validate_dataset_id("a-b")


def test_dataset_id_rejects_colon() -> None:
    with pytest.raises(InvalidName):
        validate_dataset_id("a:b")


def test_dataset_id_rejects_empty_or_too_long() -> None:
    with pytest.raises(InvalidName):
        validate_dataset_id("")
    with pytest.raises(InvalidName):
        validate_dataset_id("a" * 1025)


# table IDs

def test_table_id_accepts_alnum_underscore_dash() -> None:
    validate_table_id("events-2024_01")


def test_table_id_rejects_colon() -> None:
    with pytest.raises(InvalidName):
        validate_table_id("a:b")


# job IDs

def test_job_id_accepts_alnum_underscore_dash() -> None:
    validate_job_id("job_abc-123")


def test_job_id_rejects_dot() -> None:
    with pytest.raises(InvalidName):
        validate_job_id("a.b")


# parse paths

def test_parse_dataset_path() -> None:
    ref = parse_dataset_path("projects/my-proj/datasets/my_ds")
    assert ref == DatasetRef(project="my-proj", dataset_id="my_ds")


def test_parse_table_path() -> None:
    ref = parse_table_path("projects/my-proj/datasets/my_ds/tables/users")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_job_path() -> None:
    ref = parse_job_path("projects/my-proj/jobs/job_abc")
    assert ref == JobRef(project="my-proj", job_id="job_abc")


def test_parse_dataset_path_rejects_bad_shape() -> None:
    with pytest.raises(InvalidName):
        parse_dataset_path("projects/my-proj/dataset/my_ds")


def test_parse_dataset_path_validates_components() -> None:
    with pytest.raises(InvalidName):
        parse_dataset_path("projects/MY-PROJ/datasets/my_ds")


# three-part backtick names

def test_parse_three_part_dotted() -> None:
    ref = parse_three_part("my-proj.my_ds.users")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_three_part_with_colon_separator() -> None:
    # BQ legacy form: project:dataset.table — accepted at parse time.
    ref = parse_three_part("my-proj:my_ds.users")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_three_part_strips_backticks() -> None:
    ref = parse_three_part("`my-proj.my_ds.users`")
    assert ref == TableRef(project="my-proj", dataset_id="my_ds", table_id="users")


def test_parse_three_part_rejects_two_part() -> None:
    with pytest.raises(InvalidName):
        parse_three_part("my_ds.users")


# DuckDB identifiers

def test_duckdb_schema_name_uses_colon_separator() -> None:
    assert duckdb_schema_name("my-proj", "my_ds") == "my-proj:my_ds"


def test_duckdb_table_qualname_quotes_each_part() -> None:
    assert (
        duckdb_table_qualname("my-proj", "my_ds", "users")
        == '"my-proj:my_ds"."users"'
    )


def test_duckdb_table_qualname_validates_inputs() -> None:
    with pytest.raises(InvalidName):
        duckdb_table_qualname("BadProj", "my_ds", "users")
```

- [ ] **Step 2: Run — fails**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_names.py -v
```

Expected: `ImportError` on `gcp_local.services.bigquery.names`.

- [ ] **Step 3: Implement `src/gcp_local/services/bigquery/names.py`**

```python
"""Resource-name parsing and DuckDB identifier construction for BigQuery.

Spec §4.1 (resource names) and §5.1 (logical → DuckDB schema mapping).
"""

import re
from dataclasses import dataclass

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$|^[a-z]$")
_DATASET_RE = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
_TABLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")
_JOB_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")


class InvalidName(ValueError):
    """Raised when a project/dataset/table/job ID or path is malformed."""


@dataclass(frozen=True)
class DatasetRef:
    project: str
    dataset_id: str


@dataclass(frozen=True)
class TableRef:
    project: str
    dataset_id: str
    table_id: str


@dataclass(frozen=True)
class JobRef:
    project: str
    job_id: str


def validate_project_id(s: str) -> None:
    if not _PROJECT_RE.match(s):
        raise InvalidName(f"invalid project id: {s!r}")


def validate_dataset_id(s: str) -> None:
    if not _DATASET_RE.match(s):
        raise InvalidName(f"invalid dataset id: {s!r}")


def validate_table_id(s: str) -> None:
    if not _TABLE_RE.match(s):
        raise InvalidName(f"invalid table id: {s!r}")


def validate_job_id(s: str) -> None:
    if not _JOB_RE.match(s):
        raise InvalidName(f"invalid job id: {s!r}")


def parse_dataset_path(path: str) -> DatasetRef:
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "projects" or parts[2] != "datasets":
        raise InvalidName(f"not a dataset path: {path!r}")
    validate_project_id(parts[1])
    validate_dataset_id(parts[3])
    return DatasetRef(project=parts[1], dataset_id=parts[3])


def parse_table_path(path: str) -> TableRef:
    parts = path.split("/")
    if (
        len(parts) != 6
        or parts[0] != "projects"
        or parts[2] != "datasets"
        or parts[4] != "tables"
    ):
        raise InvalidName(f"not a table path: {path!r}")
    validate_project_id(parts[1])
    validate_dataset_id(parts[3])
    validate_table_id(parts[5])
    return TableRef(project=parts[1], dataset_id=parts[3], table_id=parts[5])


def parse_job_path(path: str) -> JobRef:
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "projects" or parts[2] != "jobs":
        raise InvalidName(f"not a job path: {path!r}")
    validate_project_id(parts[1])
    validate_job_id(parts[3])
    return JobRef(project=parts[1], job_id=parts[3])


def parse_three_part(s: str) -> TableRef:
    """Parse `project.dataset.table` or `project:dataset.table` (with optional surrounding backticks)."""
    s = s.strip().strip("`")
    if ":" in s:
        head, _, tail = s.partition(":")
        if "." not in tail:
            raise InvalidName(f"not a three-part name: {s!r}")
        ds, _, tbl = tail.partition(".")
        project, dataset_id, table_id = head, ds, tbl
    else:
        parts = s.split(".")
        if len(parts) != 3:
            raise InvalidName(f"not a three-part name: {s!r}")
        project, dataset_id, table_id = parts
    validate_project_id(project)
    validate_dataset_id(dataset_id)
    validate_table_id(table_id)
    return TableRef(project=project, dataset_id=dataset_id, table_id=table_id)


def duckdb_schema_name(project: str, dataset_id: str) -> str:
    """The unquoted DuckDB schema name backing a (project, dataset) pair."""
    validate_project_id(project)
    validate_dataset_id(dataset_id)
    return f"{project}:{dataset_id}"


def duckdb_table_qualname(project: str, dataset_id: str, table_id: str) -> str:
    """A fully-quoted `"<schema>"."<table>"` reference safe for DuckDB SQL."""
    validate_table_id(table_id)
    schema = duckdb_schema_name(project, dataset_id)
    return f'"{schema}"."{table_id}"'
```

- [ ] **Step 4: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_names.py -v
```

All 24 PASS.

- [ ] **Step 5: Quality gate**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
```

All green.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/bigquery/names.py tests/unit/services/bigquery/test_names.py
git commit -m "$(cat <<'EOF'
feat(bigquery): resource-name parser + DuckDB identifier builder

Parses BQ project/dataset/table/job paths and three-part backtick
table references; builds quoted DuckDB schema names using the
project:dataset separator from the spec.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: BigQuery type system ↔ DuckDB

Goal: a `types.py` module that:
1. Parses a BigQuery `TableSchema` (list of `FieldSchema` dicts as the REST API delivers them) into typed `FieldSchema` objects.
2. Translates that into a DuckDB `CREATE TABLE` column-type fragment.
3. Serializes a DuckDB row tuple back into BQ's wire JSON format (`{f: [{v: ...}, ...]}`), using the BQ-declared types — not DuckDB's column types — so `TIMESTAMP` vs `DATETIME` round-trip per spec §4.3.

**Files:**
- Create: `src/gcp_local/services/bigquery/models.py` (just `FieldSchema` for now; extended in Task 4)
- Create: `src/gcp_local/services/bigquery/types.py`
- Create: `tests/unit/services/bigquery/test_types.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_types.py`:

```python
import datetime as dt
from decimal import Decimal

import pytest

from gcp_local.services.bigquery.models import FieldSchema
from gcp_local.services.bigquery.types import (
    UnsupportedType,
    bq_field_to_duckdb_ddl,
    duckdb_value_to_bq_wire,
    parse_table_schema,
    schema_to_duckdb_columns,
)


def test_parse_simple_schema() -> None:
    raw = [
        {"name": "id", "type": "INT64", "mode": "REQUIRED"},
        {"name": "name", "type": "STRING"},
    ]
    fields = parse_table_schema(raw)
    assert fields == [
        FieldSchema(name="id", type="INT64", mode="REQUIRED", fields=None),
        FieldSchema(name="name", type="STRING", mode="NULLABLE", fields=None),
    ]


def test_parse_record_schema() -> None:
    raw = [
        {
            "name": "addr",
            "type": "RECORD",
            "mode": "NULLABLE",
            "fields": [
                {"name": "city", "type": "STRING"},
                {"name": "zip", "type": "STRING", "mode": "REQUIRED"},
            ],
        }
    ]
    [field] = parse_table_schema(raw)
    assert field.type == "RECORD"
    assert field.fields is not None
    assert [f.name for f in field.fields] == ["city", "zip"]


def test_parse_repeated_array() -> None:
    raw = [{"name": "tags", "type": "STRING", "mode": "REPEATED"}]
    [field] = parse_table_schema(raw)
    assert field.mode == "REPEATED"


def test_parse_rejects_geography() -> None:
    with pytest.raises(UnsupportedType, match="GEOGRAPHY"):
        parse_table_schema([{"name": "pt", "type": "GEOGRAPHY"}])


def test_parse_rejects_interval() -> None:
    with pytest.raises(UnsupportedType, match="INTERVAL"):
        parse_table_schema([{"name": "i", "type": "INTERVAL"}])


def test_parse_rejects_unknown_type() -> None:
    with pytest.raises(UnsupportedType):
        parse_table_schema([{"name": "x", "type": "BANANA"}])


def test_ddl_scalar_required() -> None:
    f = FieldSchema(name="id", type="INT64", mode="REQUIRED", fields=None)
    assert bq_field_to_duckdb_ddl(f) == '"id" BIGINT NOT NULL'


def test_ddl_scalar_nullable() -> None:
    f = FieldSchema(name="name", type="STRING", mode="NULLABLE", fields=None)
    assert bq_field_to_duckdb_ddl(f) == '"name" VARCHAR'


def test_ddl_repeated_array() -> None:
    f = FieldSchema(name="tags", type="STRING", mode="REPEATED", fields=None)
    assert bq_field_to_duckdb_ddl(f) == '"tags" VARCHAR[]'


def test_ddl_struct() -> None:
    f = FieldSchema(
        name="addr",
        type="RECORD",
        mode="NULLABLE",
        fields=[
            FieldSchema(name="city", type="STRING", mode="NULLABLE", fields=None),
            FieldSchema(name="zip", type="STRING", mode="REQUIRED", fields=None),
        ],
    )
    assert (
        bq_field_to_duckdb_ddl(f)
        == '"addr" STRUCT("city" VARCHAR, "zip" VARCHAR)'
    )


def test_ddl_repeated_struct() -> None:
    f = FieldSchema(
        name="tags",
        type="RECORD",
        mode="REPEATED",
        fields=[FieldSchema(name="k", type="STRING", mode="NULLABLE", fields=None)],
    )
    assert bq_field_to_duckdb_ddl(f) == '"tags" STRUCT("k" VARCHAR)[]'


def test_ddl_numeric_and_bignumeric() -> None:
    a = FieldSchema(name="a", type="NUMERIC", mode="NULLABLE", fields=None)
    b = FieldSchema(name="b", type="BIGNUMERIC", mode="NULLABLE", fields=None)
    assert bq_field_to_duckdb_ddl(a) == '"a" DECIMAL(38, 9)'
    assert bq_field_to_duckdb_ddl(b) == '"b" DECIMAL(38, 18)'


def test_ddl_timestamp_vs_datetime() -> None:
    ts = FieldSchema(name="ts", type="TIMESTAMP", mode="NULLABLE", fields=None)
    dtf = FieldSchema(name="d", type="DATETIME", mode="NULLABLE", fields=None)
    assert bq_field_to_duckdb_ddl(ts) == '"ts" TIMESTAMP WITH TIME ZONE'
    assert bq_field_to_duckdb_ddl(dtf) == '"d" TIMESTAMP'


def test_schema_to_duckdb_columns_joins() -> None:
    schema = [
        FieldSchema(name="id", type="INT64", mode="REQUIRED", fields=None),
        FieldSchema(name="name", type="STRING", mode="NULLABLE", fields=None),
    ]
    assert (
        schema_to_duckdb_columns(schema)
        == '"id" BIGINT NOT NULL, "name" VARCHAR'
    )


def test_wire_int() -> None:
    f = FieldSchema(name="x", type="INT64", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire(123, f) == {"v": "123"}


def test_wire_null() -> None:
    f = FieldSchema(name="x", type="INT64", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire(None, f) == {"v": None}


def test_wire_string() -> None:
    f = FieldSchema(name="x", type="STRING", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire("hello", f) == {"v": "hello"}


def test_wire_bool() -> None:
    f = FieldSchema(name="x", type="BOOL", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire(True, f) == {"v": "true"}


def test_wire_bytes_base64() -> None:
    f = FieldSchema(name="x", type="BYTES", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire(b"hi", f) == {"v": "aGk="}


def test_wire_numeric_decimal_string() -> None:
    f = FieldSchema(name="x", type="NUMERIC", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire(Decimal("3.14"), f) == {"v": "3.14"}


def test_wire_timestamp_epoch_seconds() -> None:
    f = FieldSchema(name="x", type="TIMESTAMP", mode="NULLABLE", fields=None)
    val = dt.datetime(2026, 4, 25, 12, 0, 0, tzinfo=dt.UTC)
    out = duckdb_value_to_bq_wire(val, f)
    assert out["v"] == "1777291200.000000"


def test_wire_date_iso() -> None:
    f = FieldSchema(name="x", type="DATE", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire(dt.date(2026, 4, 25), f) == {"v": "2026-04-25"}


def test_wire_repeated_string() -> None:
    f = FieldSchema(name="tags", type="STRING", mode="REPEATED", fields=None)
    assert duckdb_value_to_bq_wire(["a", "b"], f) == {
        "v": [{"v": "a"}, {"v": "b"}]
    }


def test_wire_struct() -> None:
    inner = [
        FieldSchema(name="city", type="STRING", mode="NULLABLE", fields=None),
        FieldSchema(name="zip", type="STRING", mode="REQUIRED", fields=None),
    ]
    f = FieldSchema(name="addr", type="RECORD", mode="NULLABLE", fields=inner)
    val = {"city": "NYC", "zip": "10001"}
    assert duckdb_value_to_bq_wire(val, f) == {
        "v": {"f": [{"v": "NYC"}, {"v": "10001"}]}
    }
```

- [ ] **Step 2: Run — fails**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_types.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `src/gcp_local/services/bigquery/models.py`**

```python
"""Domain records for BigQuery resources.

Extended in Task 4 with DatasetRecord/TableRecord/JobRecord.
"""

from dataclasses import dataclass
from typing import Literal

FieldMode = Literal["NULLABLE", "REQUIRED", "REPEATED"]


@dataclass(frozen=True)
class FieldSchema:
    name: str
    type: str
    mode: FieldMode
    fields: list["FieldSchema"] | None
```

- [ ] **Step 4: Implement `src/gcp_local/services/bigquery/types.py`**

```python
"""BigQuery TableSchema ↔ DuckDB type mapping + row serialization (spec §4.3)."""

import base64
import datetime as dt
from decimal import Decimal
from typing import Any, cast

from gcp_local.services.bigquery.models import FieldMode, FieldSchema

_SCALAR_DDL: dict[str, str] = {
    "STRING": "VARCHAR",
    "BYTES": "BLOB",
    "INT64": "BIGINT",
    "INTEGER": "BIGINT",
    "FLOAT64": "DOUBLE",
    "FLOAT": "DOUBLE",
    "BOOL": "BOOLEAN",
    "BOOLEAN": "BOOLEAN",
    "NUMERIC": "DECIMAL(38, 9)",
    "BIGNUMERIC": "DECIMAL(38, 18)",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP WITH TIME ZONE",
    "DATETIME": "TIMESTAMP",
    "JSON": "JSON",
}

_REJECTED: set[str] = {"GEOGRAPHY", "INTERVAL", "RANGE"}
_SUPPORTED_MODES: set[str] = {"NULLABLE", "REQUIRED", "REPEATED"}


class UnsupportedType(ValueError):
    """Raised when a BQ type isn't implemented in v1 (e.g. GEOGRAPHY)."""


def parse_table_schema(raw_fields: list[dict[str, Any]]) -> list[FieldSchema]:
    return [_parse_field(f) for f in raw_fields]


def _parse_field(raw: dict[str, Any]) -> FieldSchema:
    name = raw["name"]
    bq_type = str(raw.get("type", "")).upper()
    mode_raw = str(raw.get("mode", "NULLABLE")).upper()
    if mode_raw not in _SUPPORTED_MODES:
        raise UnsupportedType(f"unsupported field mode: {mode_raw}")
    mode = cast(FieldMode, mode_raw)
    if bq_type in _REJECTED:
        raise UnsupportedType(f"BQ type {bq_type} is not supported in gcp-local v1")
    nested: list[FieldSchema] | None = None
    if bq_type in {"RECORD", "STRUCT"}:
        sub = raw.get("fields", [])
        if not sub:
            raise UnsupportedType("RECORD field requires nested fields")
        nested = [_parse_field(s) for s in sub]
        bq_type = "RECORD"
    elif bq_type not in _SCALAR_DDL:
        raise UnsupportedType(f"unknown BQ type: {bq_type!r}")
    return FieldSchema(name=name, type=bq_type, mode=mode, fields=nested)


def bq_field_to_duckdb_ddl(field: FieldSchema) -> str:
    inner = _duckdb_inner_type(field)
    if field.mode == "REPEATED":
        inner = f"{inner}[]"
    column = f'"{field.name}" {inner}'
    if field.mode == "REQUIRED":
        column += " NOT NULL"
    return column


def _duckdb_inner_type(field: FieldSchema) -> str:
    if field.type == "RECORD":
        assert field.fields is not None
        members = ", ".join(_struct_member_ddl(f) for f in field.fields)
        return f"STRUCT({members})"
    return _SCALAR_DDL[field.type]


def _struct_member_ddl(field: FieldSchema) -> str:
    inner = _duckdb_inner_type(field)
    if field.mode == "REPEATED":
        inner = f"{inner}[]"
    return f'"{field.name}" {inner}'


def schema_to_duckdb_columns(schema: list[FieldSchema]) -> str:
    return ", ".join(bq_field_to_duckdb_ddl(f) for f in schema)


def duckdb_value_to_bq_wire(value: Any, field: FieldSchema) -> dict[str, Any]:
    if value is None:
        return {"v": None}
    if field.mode == "REPEATED":
        scalar_field = FieldSchema(
            name=field.name, type=field.type, mode="NULLABLE", fields=field.fields
        )
        return {"v": [duckdb_value_to_bq_wire(v, scalar_field) for v in value]}
    if field.type == "RECORD":
        assert field.fields is not None
        return {
            "v": {
                "f": [
                    duckdb_value_to_bq_wire(value[sub.name], sub) for sub in field.fields
                ]
            }
        }
    return {"v": _scalar_to_wire(value, field.type)}


def _scalar_to_wire(value: Any, bq_type: str) -> Any:
    match bq_type:
        case "STRING" | "JSON":
            return str(value)
        case "BYTES":
            return base64.b64encode(value).decode("ascii")
        case "INT64" | "INTEGER":
            return str(int(value))
        case "FLOAT64" | "FLOAT":
            return repr(float(value))
        case "BOOL" | "BOOLEAN":
            return "true" if bool(value) else "false"
        case "NUMERIC" | "BIGNUMERIC":
            return str(Decimal(value))
        case "DATE":
            return value.isoformat()
        case "TIME":
            return value.isoformat()
        case "TIMESTAMP":
            ts: dt.datetime = value
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.UTC)
            return f"{ts.timestamp():.6f}"
        case "DATETIME":
            return value.isoformat(sep="T", timespec="microseconds")
        case _:
            return str(value)
```

- [ ] **Step 5: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_types.py -v
```

All tests PASS.

- [ ] **Step 6: Quality gate**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
```

All green.

- [ ] **Step 7: Commit**

```bash
git add src/gcp_local/services/bigquery/models.py src/gcp_local/services/bigquery/types.py tests/unit/services/bigquery/test_types.py
git commit -m "$(cat <<'EOF'
feat(bigquery): TableSchema parsing + BQ↔DuckDB type mapping

Parses BQ TableSchema field dicts, generates DuckDB column DDL
(including STRUCT and ARRAY/REPEATED), and serializes DuckDB
result values into BQ wire JSON. Rejects GEOGRAPHY/INTERVAL/RANGE
per the spec.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Domain records (Dataset / Table / Job)

Goal: extend `models.py` with `DatasetRecord`, `TableRecord`, and `JobRecord` dataclasses plus simple JSON (de)serialization helpers used by the catalog and the REST routes.

**Files:**
- Modify: `src/gcp_local/services/bigquery/models.py`
- Create: `tests/unit/services/bigquery/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_models.py`:

```python
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    JobRecord,
    TableRecord,
    dataset_from_dict,
    dataset_to_dict,
    job_from_dict,
    job_to_dict,
    table_from_dict,
    table_to_dict,
)


def test_dataset_round_trip() -> None:
    rec = DatasetRecord(
        project="p",
        dataset_id="d",
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={"env": "dev"},
        location="US",
        default_table_expiration_ms=None,
    )
    payload = dataset_to_dict(rec)
    assert payload["labels"] == {"env": "dev"}
    rec2 = dataset_from_dict(payload)
    assert rec2 == rec


def test_table_round_trip_with_struct_schema() -> None:
    schema = [
        FieldSchema(name="id", type="INT64", mode="REQUIRED", fields=None),
        FieldSchema(
            name="addr",
            type="RECORD",
            mode="NULLABLE",
            fields=[FieldSchema(name="city", type="STRING", mode="NULLABLE", fields=None)],
        ),
    ]
    rec = TableRecord(
        project="p",
        dataset_id="d",
        table_id="t",
        schema=schema,
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description="hi",
        labels={},
        time_partitioning=None,
        range_partitioning=None,
        clustering=None,
    )
    payload = table_to_dict(rec)
    rec2 = table_from_dict(payload)
    assert rec2 == rec


def test_job_round_trip() -> None:
    rec = JobRecord(
        project="p",
        job_id="j1",
        job_type="QUERY",
        state="DONE",
        create_time="2026-04-25T00:00:00Z",
        start_time="2026-04-25T00:00:00Z",
        end_time="2026-04-25T00:00:00Z",
        user_email="local@gcp-local.invalid",
        statement_type="SELECT",
        sql="SELECT 1",
        destination_table=("_gcp_local", "_gcp_local_jobs", "_job_j1"),
        total_rows=1,
        total_bytes_processed=0,
        error_result=None,
        errors=[],
    )
    payload = job_to_dict(rec)
    assert payload["destination_table"] == ["_gcp_local", "_gcp_local_jobs", "_job_j1"]
    rec2 = job_from_dict(payload)
    assert rec2 == rec
```

- [ ] **Step 2: Run — fails** with `ImportError` on the new symbols.

- [ ] **Step 3: Extend `src/gcp_local/services/bigquery/models.py`**

Replace the file's contents with:

```python
"""Domain records for BigQuery resources."""

from dataclasses import asdict, dataclass, field as dc_field
from typing import Any, Literal, cast

FieldMode = Literal["NULLABLE", "REQUIRED", "REPEATED"]


@dataclass(frozen=True)
class FieldSchema:
    name: str
    type: str
    mode: FieldMode
    fields: list["FieldSchema"] | None


@dataclass
class DatasetRecord:
    project: str
    dataset_id: str
    create_time: str
    last_modified_time: str
    description: str | None
    labels: dict[str, str]
    location: str
    default_table_expiration_ms: int | None


@dataclass
class TableRecord:
    project: str
    dataset_id: str
    table_id: str
    schema: list[FieldSchema]
    create_time: str
    last_modified_time: str
    description: str | None
    labels: dict[str, str]
    time_partitioning: dict[str, Any] | None
    range_partitioning: dict[str, Any] | None
    clustering: dict[str, Any] | None


@dataclass
class JobRecord:
    project: str
    job_id: str
    job_type: str  # "QUERY" | "DML"
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


def _field_to_dict(f: FieldSchema) -> dict[str, Any]:
    out: dict[str, Any] = {"name": f.name, "type": f.type, "mode": f.mode}
    if f.fields is not None:
        out["fields"] = [_field_to_dict(s) for s in f.fields]
    return out


def _field_from_dict(raw: dict[str, Any]) -> FieldSchema:
    nested = (
        [_field_from_dict(s) for s in raw["fields"]] if raw.get("fields") is not None else None
    )
    return FieldSchema(
        name=raw["name"],
        type=raw["type"],
        mode=cast(FieldMode, raw["mode"]),
        fields=nested,
    )


def dataset_to_dict(rec: DatasetRecord) -> dict[str, Any]:
    return asdict(rec)


def dataset_from_dict(raw: dict[str, Any]) -> DatasetRecord:
    return DatasetRecord(
        project=raw["project"],
        dataset_id=raw["dataset_id"],
        create_time=raw["create_time"],
        last_modified_time=raw["last_modified_time"],
        description=raw["description"],
        labels=dict(raw.get("labels") or {}),
        location=raw["location"],
        default_table_expiration_ms=raw.get("default_table_expiration_ms"),
    )


def table_to_dict(rec: TableRecord) -> dict[str, Any]:
    return {
        "project": rec.project,
        "dataset_id": rec.dataset_id,
        "table_id": rec.table_id,
        "schema": [_field_to_dict(f) for f in rec.schema],
        "create_time": rec.create_time,
        "last_modified_time": rec.last_modified_time,
        "description": rec.description,
        "labels": dict(rec.labels),
        "time_partitioning": rec.time_partitioning,
        "range_partitioning": rec.range_partitioning,
        "clustering": rec.clustering,
    }


def table_from_dict(raw: dict[str, Any]) -> TableRecord:
    return TableRecord(
        project=raw["project"],
        dataset_id=raw["dataset_id"],
        table_id=raw["table_id"],
        schema=[_field_from_dict(s) for s in raw["schema"]],
        create_time=raw["create_time"],
        last_modified_time=raw["last_modified_time"],
        description=raw.get("description"),
        labels=dict(raw.get("labels") or {}),
        time_partitioning=raw.get("time_partitioning"),
        range_partitioning=raw.get("range_partitioning"),
        clustering=raw.get("clustering"),
    )


def job_to_dict(rec: JobRecord) -> dict[str, Any]:
    payload = asdict(rec)
    if rec.destination_table is not None:
        payload["destination_table"] = list(rec.destination_table)
    return payload


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
    )
```

- [ ] **Step 4: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_models.py -v
```

All 3 PASS.

- [ ] **Step 5: Quality gate + commit**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery/models.py tests/unit/services/bigquery/test_models.py
git commit -m "$(cat <<'EOF'
feat(bigquery): domain records for datasets, tables, and jobs

Dataclasses + JSON round-trip helpers used by the catalog and the
REST routes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: DuckDB connection + catalog bootstrap

Goal: a `BigQueryConnection` wrapper that owns one DuckDB connection (in-memory or file-backed), bootstraps the `_gcp_local_meta.{datasets,tables}` and `_gcp_local_jobs` schemas, and offers a `reset()` that drops every non-system schema and rebuilds the catalog. CPU-bound calls are dispatched onto a thread executor.

**Files:**
- Create: `src/gcp_local/services/bigquery/engine/__init__.py` (empty)
- Create: `src/gcp_local/services/bigquery/engine/connection.py`
- Create: `tests/unit/services/bigquery/test_connection.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_connection.py`:

```python
from pathlib import Path

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection


@pytest.mark.asyncio
async def test_in_memory_connection_bootstraps_catalog(tmp_path: Path) -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name IN ('_gcp_local_meta', '_gcp_local_jobs') "
        "ORDER BY schema_name"
    )
    assert [r[0] for r in rows] == ["_gcp_local_jobs", "_gcp_local_meta"]
    rows = await conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = '_gcp_local_meta' ORDER BY table_name"
    )
    assert [r[0] for r in rows] == ["datasets", "tables"]
    await conn.shutdown()


@pytest.mark.asyncio
async def test_disk_connection_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "bq.duckdb"
    conn = BigQueryConnection.on_disk(db_path)
    await conn.startup()
    await conn.execute(
        "INSERT INTO _gcp_local_meta.datasets VALUES ('p', 'd', '{}')"
    )
    await conn.shutdown()

    conn2 = BigQueryConnection.on_disk(db_path)
    await conn2.startup()
    rows = await conn2.execute(
        "SELECT project, dataset_id FROM _gcp_local_meta.datasets"
    )
    assert rows == [("p", "d")]
    await conn2.shutdown()


@pytest.mark.asyncio
async def test_reset_drops_user_schemas_keeps_catalog() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    await conn.execute('CREATE SCHEMA "p:d"')
    await conn.execute('CREATE TABLE "p:d"."t" (x BIGINT)')
    await conn.execute("INSERT INTO _gcp_local_meta.datasets VALUES ('p', 'd', '{}')")

    await conn.reset()

    rows = await conn.execute(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'p:d'"
    )
    assert rows == []
    rows = await conn.execute("SELECT count(*) FROM _gcp_local_meta.datasets")
    assert rows == [(0,)]
    await conn.shutdown()


@pytest.mark.asyncio
async def test_execute_runs_off_event_loop() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute("SELECT 1 + 1")
    assert rows == [(2,)]
    await conn.shutdown()
```

- [ ] **Step 2: Run — fails** with `ImportError`.

- [ ] **Step 3: Implement `src/gcp_local/services/bigquery/engine/connection.py`**

```python
"""DuckDB connection lifecycle + catalog bootstrap (spec §5)."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb


_CATALOG_DDL = [
    "CREATE SCHEMA IF NOT EXISTS _gcp_local_meta",
    "CREATE SCHEMA IF NOT EXISTS _gcp_local_jobs",
    """
    CREATE TABLE IF NOT EXISTS _gcp_local_meta.datasets (
        project    VARCHAR NOT NULL,
        dataset_id VARCHAR NOT NULL,
        record     JSON    NOT NULL,
        PRIMARY KEY (project, dataset_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _gcp_local_meta.tables (
        project    VARCHAR NOT NULL,
        dataset_id VARCHAR NOT NULL,
        table_id   VARCHAR NOT NULL,
        record     JSON    NOT NULL,
        PRIMARY KEY (project, dataset_id, table_id)
    )
    """,
]

_SYSTEM_SCHEMAS = {
    "main",
    "information_schema",
    "pg_catalog",
    "_gcp_local_meta",
    "_gcp_local_jobs",
}


class BigQueryConnection:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bq-duckdb")
        self._conn: duckdb.DuckDBPyConnection | None = None

    @classmethod
    def in_memory(cls) -> "BigQueryConnection":
        return cls(":memory:")

    @classmethod
    def on_disk(cls, path: Path) -> "BigQueryConnection":
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(str(path))

    async def startup(self) -> None:
        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(self._executor, duckdb.connect, self._db_path)
        for ddl in _CATALOG_DDL:
            await self.execute(ddl)

    async def shutdown(self) -> None:
        if self._conn is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._conn.close)
            self._conn = None
        self._executor.shutdown(wait=True)

    async def execute(
        self, sql: str, params: list[Any] | None = None
    ) -> list[tuple[Any, ...]]:
        assert self._conn is not None, "startup() not called"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._sync_execute, sql, params or [])

    def _sync_execute(self, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
        assert self._conn is not None
        cur = self._conn.execute(sql, params)
        try:
            return cur.fetchall()
        except duckdb.InvalidInputException:
            return []

    async def reset(self) -> None:
        rows = await self.execute(
            "SELECT schema_name FROM information_schema.schemata"
        )
        for (schema,) in rows:
            if schema in _SYSTEM_SCHEMAS:
                continue
            await self.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        # Drop and recreate the transient jobs schema, plus clear catalog rows.
        await self.execute("DROP SCHEMA IF EXISTS _gcp_local_jobs CASCADE")
        await self.execute("CREATE SCHEMA _gcp_local_jobs")
        await self.execute("DELETE FROM _gcp_local_meta.tables")
        await self.execute("DELETE FROM _gcp_local_meta.datasets")
```

- [ ] **Step 4: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_connection.py -v
```

All 4 PASS.

- [ ] **Step 5: Quality gate + commit**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery/engine tests/unit/services/bigquery/test_connection.py
git commit -m "$(cat <<'EOF'
feat(bigquery): DuckDB connection + catalog bootstrap

Owns one DuckDB connection (memory or file), bootstraps the
_gcp_local_meta (datasets/tables) and _gcp_local_jobs schemas,
runs all SQL on a dedicated thread executor, and resets cleanly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Storage CRUD for datasets and tables

Goal: a `BigQueryStorage` class backed by the catalog tables in DuckDB. Provides async CRUD for datasets and tables. Creating a table also issues a `CREATE TABLE` in the dataset's user-facing schema; deleting it does the inverse.

**Files:**
- Create: `src/gcp_local/services/bigquery/storage.py`
- Create: `tests/unit/services/bigquery/test_storage.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_storage.py`:

```python
from pathlib import Path

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetAlreadyExists,
    DatasetNotFound,
    TableAlreadyExists,
    TableNotFound,
)


def _ds(project: str = "p", dataset_id: str = "d") -> DatasetRecord:
    return DatasetRecord(
        project=project,
        dataset_id=dataset_id,
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={},
        location="US",
        default_table_expiration_ms=None,
    )


def _tbl(table_id: str = "t", schema: list[FieldSchema] | None = None) -> TableRecord:
    return TableRecord(
        project="p",
        dataset_id="d",
        table_id=table_id,
        schema=schema or [FieldSchema(name="x", type="INT64", mode="NULLABLE", fields=None)],
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={},
        time_partitioning=None,
        range_partitioning=None,
        clustering=None,
    )


@pytest.fixture
async def storage() -> BigQueryStorage:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    return BigQueryStorage(conn)


@pytest.mark.asyncio
async def test_dataset_create_get(storage: BigQueryStorage) -> None:
    rec = _ds()
    await storage.create_dataset(rec)
    got = await storage.get_dataset("p", "d")
    assert got == rec


@pytest.mark.asyncio
async def test_dataset_create_duplicate_raises(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    with pytest.raises(DatasetAlreadyExists):
        await storage.create_dataset(_ds())


@pytest.mark.asyncio
async def test_dataset_get_missing_raises(storage: BigQueryStorage) -> None:
    with pytest.raises(DatasetNotFound):
        await storage.get_dataset("p", "d")


@pytest.mark.asyncio
async def test_dataset_list(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds(dataset_id="a"))
    await storage.create_dataset(_ds(dataset_id="b"))
    listed = await storage.list_datasets("p")
    assert [d.dataset_id for d in listed] == ["a", "b"]


@pytest.mark.asyncio
async def test_dataset_update(storage: BigQueryStorage) -> None:
    rec = _ds()
    await storage.create_dataset(rec)
    rec.description = "hi"
    rec.labels = {"env": "dev"}
    await storage.update_dataset(rec)
    got = await storage.get_dataset("p", "d")
    assert got.description == "hi"
    assert got.labels == {"env": "dev"}


@pytest.mark.asyncio
async def test_dataset_delete_cascades_to_tables(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    await storage.delete_dataset("p", "d", delete_contents=True)
    with pytest.raises(DatasetNotFound):
        await storage.get_dataset("p", "d")


@pytest.mark.asyncio
async def test_dataset_delete_non_empty_without_flag_raises(
    storage: BigQueryStorage,
) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    with pytest.raises(ValueError, match="not empty"):
        await storage.delete_dataset("p", "d", delete_contents=False)


@pytest.mark.asyncio
async def test_table_create_get_creates_duckdb_table(
    storage: BigQueryStorage,
) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    got = await storage.get_table("p", "d", "t")
    assert got.table_id == "t"
    # DuckDB-side table exists in the project:dataset schema.
    rows = await storage.connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'p:d' ORDER BY table_name"
    )
    assert [r[0] for r in rows] == ["t"]


@pytest.mark.asyncio
async def test_table_create_duplicate_raises(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    with pytest.raises(TableAlreadyExists):
        await storage.create_table(_tbl())


@pytest.mark.asyncio
async def test_table_get_missing_raises(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    with pytest.raises(TableNotFound):
        await storage.get_table("p", "d", "t")


@pytest.mark.asyncio
async def test_table_list(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl(table_id="a"))
    await storage.create_table(_tbl(table_id="b"))
    listed = await storage.list_tables("p", "d")
    assert [t.table_id for t in listed] == ["a", "b"]


@pytest.mark.asyncio
async def test_table_delete_drops_duckdb_table(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    await storage.delete_table("p", "d", "t")
    with pytest.raises(TableNotFound):
        await storage.get_table("p", "d", "t")
    rows = await storage.connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'p:d'"
    )
    assert rows == []
```

- [ ] **Step 2: Run — fails** with `ImportError`.

- [ ] **Step 3: Implement `src/gcp_local/services/bigquery/storage.py`**

```python
"""BigQuery dataset/table storage backed by the DuckDB catalog."""

import json

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    TableRecord,
    dataset_from_dict,
    dataset_to_dict,
    table_from_dict,
    table_to_dict,
)
from gcp_local.services.bigquery.names import (
    duckdb_schema_name,
    duckdb_table_qualname,
)
from gcp_local.services.bigquery.types import schema_to_duckdb_columns


class DatasetNotFound(KeyError):
    pass


class DatasetAlreadyExists(KeyError):
    pass


class TableNotFound(KeyError):
    pass


class TableAlreadyExists(KeyError):
    pass


class BigQueryStorage:
    def __init__(self, connection: BigQueryConnection) -> None:
        self._conn = connection

    @property
    def connection(self) -> BigQueryConnection:
        return self._conn

    # --- datasets -----------------------------------------------------

    async def create_dataset(self, rec: DatasetRecord) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [rec.project, rec.dataset_id],
        )
        if rows:
            raise DatasetAlreadyExists(f"{rec.project}:{rec.dataset_id}")
        schema_name = duckdb_schema_name(rec.project, rec.dataset_id)
        await self._conn.execute(f'CREATE SCHEMA "{schema_name}"')
        await self._conn.execute(
            "INSERT INTO _gcp_local_meta.datasets VALUES (?, ?, ?)",
            [rec.project, rec.dataset_id, json.dumps(dataset_to_dict(rec))],
        )

    async def get_dataset(self, project: str, dataset_id: str) -> DatasetRecord:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        if not rows:
            raise DatasetNotFound(f"{project}:{dataset_id}")
        return dataset_from_dict(json.loads(rows[0][0]))

    async def list_datasets(self, project: str) -> list[DatasetRecord]:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.datasets WHERE project=? ORDER BY dataset_id",
            [project],
        )
        return [dataset_from_dict(json.loads(r[0])) for r in rows]

    async def update_dataset(self, rec: DatasetRecord) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [rec.project, rec.dataset_id],
        )
        if not rows:
            raise DatasetNotFound(f"{rec.project}:{rec.dataset_id}")
        await self._conn.execute(
            "UPDATE _gcp_local_meta.datasets SET record=? WHERE project=? AND dataset_id=?",
            [json.dumps(dataset_to_dict(rec)), rec.project, rec.dataset_id],
        )

    async def delete_dataset(
        self, project: str, dataset_id: str, *, delete_contents: bool
    ) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        if not rows:
            raise DatasetNotFound(f"{project}:{dataset_id}")
        tbls = await self._conn.execute(
            "SELECT count(*) FROM _gcp_local_meta.tables WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        if tbls and tbls[0][0] and not delete_contents:
            raise ValueError(f"dataset {project}:{dataset_id} is not empty")
        schema_name = duckdb_schema_name(project, dataset_id)
        await self._conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await self._conn.execute(
            "DELETE FROM _gcp_local_meta.tables WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        await self._conn.execute(
            "DELETE FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )

    # --- tables -------------------------------------------------------

    async def create_table(self, rec: TableRecord) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.tables WHERE project=? AND dataset_id=? AND table_id=?",
            [rec.project, rec.dataset_id, rec.table_id],
        )
        if rows:
            raise TableAlreadyExists(f"{rec.project}:{rec.dataset_id}.{rec.table_id}")
        # Make sure the dataset exists.
        await self.get_dataset(rec.project, rec.dataset_id)
        qualname = duckdb_table_qualname(rec.project, rec.dataset_id, rec.table_id)
        cols = schema_to_duckdb_columns(rec.schema)
        await self._conn.execute(f"CREATE TABLE {qualname} ({cols})")
        await self._conn.execute(
            "INSERT INTO _gcp_local_meta.tables VALUES (?, ?, ?, ?)",
            [
                rec.project,
                rec.dataset_id,
                rec.table_id,
                json.dumps(table_to_dict(rec)),
            ],
        )

    async def get_table(
        self, project: str, dataset_id: str, table_id: str
    ) -> TableRecord:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.tables "
            "WHERE project=? AND dataset_id=? AND table_id=?",
            [project, dataset_id, table_id],
        )
        if not rows:
            raise TableNotFound(f"{project}:{dataset_id}.{table_id}")
        return table_from_dict(json.loads(rows[0][0]))

    async def list_tables(
        self, project: str, dataset_id: str
    ) -> list[TableRecord]:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.tables "
            "WHERE project=? AND dataset_id=? ORDER BY table_id",
            [project, dataset_id],
        )
        return [table_from_dict(json.loads(r[0])) for r in rows]

    async def update_table(self, rec: TableRecord) -> None:
        await self.get_table(rec.project, rec.dataset_id, rec.table_id)
        await self._conn.execute(
            "UPDATE _gcp_local_meta.tables SET record=? "
            "WHERE project=? AND dataset_id=? AND table_id=?",
            [
                json.dumps(table_to_dict(rec)),
                rec.project,
                rec.dataset_id,
                rec.table_id,
            ],
        )

    async def delete_table(
        self, project: str, dataset_id: str, table_id: str
    ) -> None:
        await self.get_table(project, dataset_id, table_id)
        qualname = duckdb_table_qualname(project, dataset_id, table_id)
        await self._conn.execute(f"DROP TABLE {qualname}")
        await self._conn.execute(
            "DELETE FROM _gcp_local_meta.tables "
            "WHERE project=? AND dataset_id=? AND table_id=?",
            [project, dataset_id, table_id],
        )
```

- [ ] **Step 4: Run — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_storage.py -v
```

All tests PASS.

- [ ] **Step 5: Quality gate + commit**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery/storage.py tests/unit/services/bigquery/test_storage.py
git commit -m "$(cat <<'EOF'
feat(bigquery): dataset/table CRUD storage backed by DuckDB catalog

The catalog (project, dataset, record JSON) lives in
_gcp_local_meta inside the same DuckDB DB. Creating a table also
issues a DuckDB CREATE TABLE in the project:dataset schema;
deleting drops it. Dataset deletes cascade when delete_contents=True.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Error envelope helper + datasets REST routes + service wiring

Goal: a shared `errors.py` that maps internal exceptions to BQ REST envelopes, and the first batch of REST routes (`datasets.*`) wired into `app.py`. Also refactor `service.py` to own a `BigQueryConnection` + `BigQueryStorage` and pass them to the app.

**Files:**
- Create: `src/gcp_local/services/bigquery/errors.py`
- Create: `src/gcp_local/services/bigquery/routes/__init__.py` (empty)
- Create: `src/gcp_local/services/bigquery/routes/datasets.py`
- Modify: `src/gcp_local/services/bigquery/app.py`
- Modify: `src/gcp_local/services/bigquery/service.py`
- Create: `tests/unit/services/bigquery/test_errors.py`
- Create: `tests/unit/services/bigquery/test_routes_datasets.py`

- [ ] **Step 1: Write the failing test for errors**

`tests/unit/services/bigquery/test_errors.py`:

```python
from gcp_local.services.bigquery.errors import bigquery_error_response
from gcp_local.services.bigquery.storage import (
    DatasetAlreadyExists,
    DatasetNotFound,
)
from gcp_local.services.bigquery.types import UnsupportedType
from gcp_local.services.bigquery.names import InvalidName


def test_not_found_envelope() -> None:
    resp = bigquery_error_response(DatasetNotFound("p:d"))
    assert resp.status_code == 404
    body = resp.body_dict
    assert body["error"]["code"] == 404
    assert body["error"]["status"] == "NOT_FOUND"
    assert body["error"]["errors"][0]["reason"] == "notFound"


def test_already_exists_envelope() -> None:
    resp = bigquery_error_response(DatasetAlreadyExists("p:d"))
    assert resp.status_code == 409
    assert resp.body_dict["error"]["errors"][0]["reason"] == "duplicate"


def test_invalid_name_envelope() -> None:
    resp = bigquery_error_response(InvalidName("BAD"))
    assert resp.status_code == 400
    assert resp.body_dict["error"]["errors"][0]["reason"] == "invalid"


def test_unsupported_type_envelope() -> None:
    resp = bigquery_error_response(UnsupportedType("GEOGRAPHY"))
    assert resp.status_code == 400
    assert resp.body_dict["error"]["errors"][0]["reason"] == "invalid"


def test_uncaught_envelope() -> None:
    resp = bigquery_error_response(RuntimeError("boom"))
    assert resp.status_code == 500
    assert resp.body_dict["error"]["errors"][0]["reason"] == "internalError"
```

- [ ] **Step 2: Implement `src/gcp_local/services/bigquery/errors.py`**

```python
"""BigQuery REST error envelope helper (spec §10)."""

from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse

from gcp_local.services.bigquery.names import InvalidName
from gcp_local.services.bigquery.storage import (
    DatasetAlreadyExists,
    DatasetNotFound,
    TableAlreadyExists,
    TableNotFound,
)
from gcp_local.services.bigquery.types import UnsupportedType


class JobNotFound(KeyError):
    pass


class InvalidQuery(ValueError):
    pass


class InvalidValue(ValueError):
    pass


_STATUS_MAP: list[tuple[type[Exception], int, str, str]] = [
    (DatasetNotFound, 404, "notFound", "NOT_FOUND"),
    (TableNotFound, 404, "notFound", "NOT_FOUND"),
    (JobNotFound, 404, "notFound", "NOT_FOUND"),
    (DatasetAlreadyExists, 409, "duplicate", "ALREADY_EXISTS"),
    (TableAlreadyExists, 409, "duplicate", "ALREADY_EXISTS"),
    (InvalidName, 400, "invalid", "INVALID_ARGUMENT"),
    (UnsupportedType, 400, "invalid", "INVALID_ARGUMENT"),
    (InvalidValue, 400, "invalid", "INVALID_ARGUMENT"),
    (InvalidQuery, 400, "invalidQuery", "INVALID_ARGUMENT"),
]


@dataclass
class _Resp:
    status_code: int
    body_dict: dict[str, Any]

    def to_response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status_code, content=self.body_dict)


def bigquery_error_response(exc: BaseException) -> _Resp:
    for cls, status, reason, status_str in _STATUS_MAP:
        if isinstance(exc, cls):
            return _build(status, str(exc) or cls.__name__, reason, status_str)
    return _build(500, str(exc) or "internal error", "internalError", "INTERNAL")


def _build(code: int, message: str, reason: str, status_str: str) -> _Resp:
    return _Resp(
        status_code=code,
        body_dict={
            "error": {
                "code": code,
                "message": message,
                "errors": [
                    {"reason": reason, "message": message, "domain": "global"}
                ],
                "status": status_str,
            }
        },
    )
```

- [ ] **Step 3: Run errors test — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_errors.py -v
```

All 5 PASS.

- [ ] **Step 4: Write the failing test for datasets routes**

`tests/unit/services/bigquery/test_routes_datasets.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> TestClient:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    app = build_app(storage=storage)
    return TestClient(app)


def test_create_dataset_201(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/my-proj/datasets",
        json={
            "datasetReference": {"projectId": "my-proj", "datasetId": "my_ds"},
            "labels": {"env": "dev"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "bigquery#dataset"
    assert body["datasetReference"] == {"projectId": "my-proj", "datasetId": "my_ds"}
    assert body["labels"] == {"env": "dev"}


def test_get_dataset(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/my-proj/datasets",
        json={"datasetReference": {"projectId": "my-proj", "datasetId": "my_ds"}},
    )
    r = client.get("/bigquery/v2/projects/my-proj/datasets/my_ds")
    assert r.status_code == 200
    assert r.json()["datasetReference"]["datasetId"] == "my_ds"


def test_get_dataset_404(client: TestClient) -> None:
    r = client.get("/bigquery/v2/projects/my-proj/datasets/missing")
    assert r.status_code == 404
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


def test_create_duplicate_409(client: TestClient) -> None:
    body = {"datasetReference": {"projectId": "p", "datasetId": "d"}}
    client.post("/bigquery/v2/projects/p/datasets", json=body)
    r = client.post("/bigquery/v2/projects/p/datasets", json=body)
    assert r.status_code == 409


def test_list_datasets(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "a"}},
    )
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "b"}},
    )
    r = client.get("/bigquery/v2/projects/p/datasets")
    assert r.status_code == 200
    ids = [d["datasetReference"]["datasetId"] for d in r.json()["datasets"]]
    assert ids == ["a", "b"]


def test_delete_dataset(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    r = client.delete("/bigquery/v2/projects/p/datasets/d")
    assert r.status_code == 204
    r2 = client.get("/bigquery/v2/projects/p/datasets/d")
    assert r2.status_code == 404


def test_patch_dataset(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    r = client.patch(
        "/bigquery/v2/projects/p/datasets/d",
        json={"description": "hello", "labels": {"env": "dev"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "hello"
    assert body["labels"] == {"env": "dev"}
```

- [ ] **Step 5: Run — fails** (TestClient asks for `build_app` with a `storage` kwarg that doesn't exist yet, and the routes don't exist).

- [ ] **Step 6: Implement `src/gcp_local/services/bigquery/routes/datasets.py`**

```python
"""REST handlers for /bigquery/v2/projects/{project}/datasets/*."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Body, Path, Response

from gcp_local.services.bigquery.errors import (
    InvalidValue,
    bigquery_error_response,
)
from gcp_local.services.bigquery.models import DatasetRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_dataset_id,
    validate_project_id,
)
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetAlreadyExists,
    DatasetNotFound,
)


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _to_api(rec: DatasetRecord) -> dict[str, Any]:
    return {
        "kind": "bigquery#dataset",
        "id": f"{rec.project}:{rec.dataset_id}",
        "datasetReference": {
            "projectId": rec.project,
            "datasetId": rec.dataset_id,
        },
        "creationTime": rec.create_time,
        "lastModifiedTime": rec.last_modified_time,
        "description": rec.description,
        "labels": rec.labels,
        "location": rec.location,
        "defaultTableExpirationMs": rec.default_table_expiration_ms,
    }


def build_router(storage: BigQueryStorage) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post("/{project}/datasets")
    async def insert_dataset(
        project: str = Path(...),
        body: dict[str, Any] = Body(...),
    ) -> Any:
        try:
            validate_project_id(project)
            ref = body.get("datasetReference") or {}
            dataset_id = ref.get("datasetId") or ""
            if ref.get("projectId") and ref["projectId"] != project:
                raise InvalidValue(
                    f"datasetReference.projectId {ref['projectId']!r} != {project!r}"
                )
            validate_dataset_id(dataset_id)
            now = _now_iso()
            rec = DatasetRecord(
                project=project,
                dataset_id=dataset_id,
                create_time=now,
                last_modified_time=now,
                description=body.get("description"),
                labels=dict(body.get("labels") or {}),
                location=body.get("location") or "US",
                default_table_expiration_ms=body.get("defaultTableExpirationMs"),
            )
            await storage.create_dataset(rec)
            return _to_api(rec)
        except (DatasetAlreadyExists, InvalidName, InvalidValue) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/datasets/{dataset_id}")
    async def get_dataset(project: str, dataset_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            rec = await storage.get_dataset(project, dataset_id)
            return _to_api(rec)
        except (DatasetNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/datasets")
    async def list_datasets(project: str) -> Any:
        try:
            validate_project_id(project)
            recs = await storage.list_datasets(project)
            return {
                "kind": "bigquery#datasetList",
                "datasets": [_to_api(r) for r in recs],
            }
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.delete("/{project}/datasets/{dataset_id}", status_code=204)
    async def delete_dataset(project: str, dataset_id: str, deleteContents: bool = False) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            await storage.delete_dataset(
                project, dataset_id, delete_contents=deleteContents
            )
            return Response(status_code=204)
        except (DatasetNotFound, InvalidName, ValueError) as e:
            return bigquery_error_response(e).to_response()

    @router.patch("/{project}/datasets/{dataset_id}")
    @router.put("/{project}/datasets/{dataset_id}")
    async def patch_dataset(
        project: str,
        dataset_id: str,
        body: dict[str, Any] = Body(...),
    ) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            rec = await storage.get_dataset(project, dataset_id)
            if "description" in body:
                rec.description = body["description"]
            if "labels" in body:
                rec.labels = dict(body["labels"] or {})
            if "defaultTableExpirationMs" in body:
                rec.default_table_expiration_ms = body["defaultTableExpirationMs"]
            rec.last_modified_time = _now_iso()
            await storage.update_dataset(rec)
            return _to_api(rec)
        except (DatasetNotFound, InvalidName, InvalidValue) as e:
            return bigquery_error_response(e).to_response()

    return router
```

- [ ] **Step 7: Update `src/gcp_local/services/bigquery/app.py`**

```python
from fastapi import FastAPI

from gcp_local.services.bigquery.routes.datasets import (
    build_router as datasets_router,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


def build_app(storage: BigQueryStorage) -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    return app
```

- [ ] **Step 8: Update `src/gcp_local/services/bigquery/service.py`**

Replace the file with:

```python
import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.storage import BigQueryStorage

log = logging.getLogger(__name__)

_DEFAULT_PORT = 9050


class BigQueryService:
    """Emulates Google BigQuery over a REST API."""

    name = "bigquery"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._connection: BigQueryConnection | None = None
        self._storage: BigQueryStorage | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        self._connection = self._make_connection(ctx)
        await self._connection.startup()
        self._storage = BigQueryStorage(self._connection)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = build_app(storage=self._storage)
        self._server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(
            self._server.serve(), name=f"{self.name}-server"
        )
        self._started = True
        log.info("bigquery service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        if self._connection is not None:
            await self._connection.shutdown()
        self._started = False

    async def reset_state(self) -> None:
        if self._connection is not None:
            await self._connection.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self._started, message="running" if self._started else "stopped"
        )

    def _make_connection(self, ctx: Context) -> BigQueryConnection:
        if ctx.persist:
            db_path = Path(ctx.data_dir) / "bigquery.duckdb"
            return BigQueryConnection.on_disk(db_path)
        return BigQueryConnection.in_memory()
```

- [ ] **Step 9: Run all** — pass

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery -v
```

All tests PASS.

- [ ] **Step 10: Quality gate + commit**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery tests/unit/services/bigquery
git commit -m "$(cat <<'EOF'
feat(bigquery): error envelope + datasets routes wired into service

Adds the shared REST error-envelope helper, /bigquery/v2/projects/
{p}/datasets handlers (insert/get/list/patch/delete), and wires
the service through BigQueryConnection + BigQueryStorage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Tables REST routes

Goal: `/bigquery/v2/projects/{p}/datasets/{d}/tables/*` handlers (insert, get, list, patch/put, delete). Schema is parsed via `parse_table_schema` (Task 3) on insert; rejects GEOGRAPHY/INTERVAL/RANGE.

**Files:**
- Create: `src/gcp_local/services/bigquery/routes/tables.py`
- Modify: `src/gcp_local/services/bigquery/app.py` (include tables router)
- Create: `tests/unit/services/bigquery/test_routes_tables.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_routes_tables.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> TestClient:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    c = TestClient(build_app(storage=storage))
    c.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    return c


def test_create_table(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                    {"name": "name", "type": "STRING"},
                ]
            },
            "labels": {"env": "dev"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "bigquery#table"
    assert body["tableReference"]["tableId"] == "t"
    assert [f["name"] for f in body["schema"]["fields"]] == ["id", "name"]


def test_get_table(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    r = client.get("/bigquery/v2/projects/p/datasets/d/tables/t")
    assert r.status_code == 200
    assert r.json()["tableReference"]["tableId"] == "t"


def test_list_tables(client: TestClient) -> None:
    for tid in ("a", "b"):
        client.post(
            "/bigquery/v2/projects/p/datasets/d/tables",
            json={
                "tableReference": {"projectId": "p", "datasetId": "d", "tableId": tid},
                "schema": {"fields": [{"name": "id", "type": "INT64"}]},
            },
        )
    r = client.get("/bigquery/v2/projects/p/datasets/d/tables")
    assert r.status_code == 200
    ids = [t["tableReference"]["tableId"] for t in r.json()["tables"]]
    assert ids == ["a", "b"]


def test_create_rejects_geography(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "g"},
            "schema": {"fields": [{"name": "loc", "type": "GEOGRAPHY"}]},
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["errors"][0]["reason"] == "invalid"


def test_delete_table(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    r = client.delete("/bigquery/v2/projects/p/datasets/d/tables/t")
    assert r.status_code == 204
    assert client.get("/bigquery/v2/projects/p/datasets/d/tables/t").status_code == 404


def test_patch_table(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    r = client.patch(
        "/bigquery/v2/projects/p/datasets/d/tables/t",
        json={"description": "hi", "labels": {"a": "b"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "hi"
    assert body["labels"] == {"a": "b"}


def test_create_in_missing_dataset_404(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/missing/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "missing", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Implement `src/gcp_local/services/bigquery/routes/tables.py`**

```python
"""REST handlers for /bigquery/v2/projects/{p}/datasets/{d}/tables/*."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Body, Response

from gcp_local.services.bigquery.errors import (
    InvalidValue,
    bigquery_error_response,
)
from gcp_local.services.bigquery.models import FieldSchema, TableRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_dataset_id,
    validate_project_id,
    validate_table_id,
)
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetNotFound,
    TableAlreadyExists,
    TableNotFound,
)
from gcp_local.services.bigquery.types import UnsupportedType, parse_table_schema


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _field_to_api(f: FieldSchema) -> dict[str, Any]:
    out: dict[str, Any] = {"name": f.name, "type": f.type, "mode": f.mode}
    if f.fields is not None:
        out["fields"] = [_field_to_api(s) for s in f.fields]
    return out


def _to_api(rec: TableRecord) -> dict[str, Any]:
    return {
        "kind": "bigquery#table",
        "id": f"{rec.project}:{rec.dataset_id}.{rec.table_id}",
        "tableReference": {
            "projectId": rec.project,
            "datasetId": rec.dataset_id,
            "tableId": rec.table_id,
        },
        "schema": {"fields": [_field_to_api(f) for f in rec.schema]},
        "creationTime": rec.create_time,
        "lastModifiedTime": rec.last_modified_time,
        "description": rec.description,
        "labels": rec.labels,
        "timePartitioning": rec.time_partitioning,
        "rangePartitioning": rec.range_partitioning,
        "clustering": rec.clustering,
        "type": "TABLE",
    }


def build_router(storage: BigQueryStorage) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post("/{project}/datasets/{dataset_id}/tables")
    async def insert_table(
        project: str,
        dataset_id: str,
        body: dict[str, Any] = Body(...),
    ) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            ref = body.get("tableReference") or {}
            table_id = ref.get("tableId") or ""
            validate_table_id(table_id)
            schema = parse_table_schema(
                ((body.get("schema") or {}).get("fields") or [])
            )
            now = _now_iso()
            rec = TableRecord(
                project=project,
                dataset_id=dataset_id,
                table_id=table_id,
                schema=schema,
                create_time=now,
                last_modified_time=now,
                description=body.get("description"),
                labels=dict(body.get("labels") or {}),
                time_partitioning=body.get("timePartitioning"),
                range_partitioning=body.get("rangePartitioning"),
                clustering=body.get("clustering"),
            )
            await storage.create_table(rec)
            return _to_api(rec)
        except (
            DatasetNotFound,
            TableAlreadyExists,
            InvalidName,
            InvalidValue,
            UnsupportedType,
        ) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/datasets/{dataset_id}/tables/{table_id}")
    async def get_table(project: str, dataset_id: str, table_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            validate_table_id(table_id)
            rec = await storage.get_table(project, dataset_id, table_id)
            return _to_api(rec)
        except (TableNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/datasets/{dataset_id}/tables")
    async def list_tables(project: str, dataset_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            recs = await storage.list_tables(project, dataset_id)
            return {
                "kind": "bigquery#tableList",
                "tables": [_to_api(r) for r in recs],
            }
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.delete(
        "/{project}/datasets/{dataset_id}/tables/{table_id}", status_code=204
    )
    async def delete_table(project: str, dataset_id: str, table_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            validate_table_id(table_id)
            await storage.delete_table(project, dataset_id, table_id)
            return Response(status_code=204)
        except (TableNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.patch("/{project}/datasets/{dataset_id}/tables/{table_id}")
    @router.put("/{project}/datasets/{dataset_id}/tables/{table_id}")
    async def patch_table(
        project: str,
        dataset_id: str,
        table_id: str,
        body: dict[str, Any] = Body(...),
    ) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            validate_table_id(table_id)
            rec = await storage.get_table(project, dataset_id, table_id)
            if "description" in body:
                rec.description = body["description"]
            if "labels" in body:
                rec.labels = dict(body["labels"] or {})
            rec.last_modified_time = _now_iso()
            await storage.update_table(rec)
            return _to_api(rec)
        except (TableNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    return router
```

- [ ] **Step 3: Update `app.py`** to include the tables router:

```python
from fastapi import FastAPI

from gcp_local.services.bigquery.routes.datasets import (
    build_router as datasets_router,
)
from gcp_local.services.bigquery.routes.tables import (
    build_router as tables_router,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


def build_app(storage: BigQueryStorage) -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    app.include_router(tables_router(storage))
    return app
```

- [ ] **Step 4: Run tests — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery -v
```

- [ ] **Step 5: Quality gate + commit**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery tests/unit/services/bigquery
git commit -m "$(cat <<'EOF'
feat(bigquery): tables REST routes

Insert/get/list/patch/delete handlers for tables. Schema parsed
on insert; GEOGRAPHY/INTERVAL/RANGE rejected at table create.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: SQL translation pipeline + function shims

Goal: `engine/translate.py` runs incoming BigQuery SQL through sqlglot, applies AST passes (three-part-name rewrite, wildcard-table expansion, `SAFE.<fn>` rewrite, `INFORMATION_SCHEMA` resolution, partitioning DDL strip, ML/geo/scripting rejection), and emits DuckDB SQL. `engine/shims.py` registers BQ-only Python UDFs on the connection (`GENERATE_UUID`, `FORMAT_DATE`/`PARSE_DATE`/`FORMAT_TIMESTAMP`/`PARSE_TIMESTAMP`).

This is the largest remaining task. To keep it manageable, split into two sub-commits.

**Files:**
- Create: `src/gcp_local/services/bigquery/engine/translate.py`
- Create: `src/gcp_local/services/bigquery/engine/info_schema.py`
- Create: `src/gcp_local/services/bigquery/engine/shims.py`
- Modify: `src/gcp_local/services/bigquery/engine/connection.py` (call `register_shims` after bootstrap)
- Create: `tests/unit/services/bigquery/test_translate.py`
- Create: `tests/unit/services/bigquery/test_info_schema.py`
- Create: `tests/unit/services/bigquery/test_shims.py`

### Sub-commit 9a: translation pipeline + INFORMATION_SCHEMA rewrite

- [ ] **Step 1: Write the failing test for translate**

`tests/unit/services/bigquery/test_translate.py`:

```python
import pytest

from gcp_local.services.bigquery.engine.translate import (
    UnsupportedSql,
    translate,
)


class FakeCatalog:
    def __init__(self, tables: dict[tuple[str, str], list[str]]) -> None:
        self._tables = tables

    def list_table_ids(self, project: str, dataset_id: str) -> list[str]:
        return list(self._tables.get((project, dataset_id), []))


def test_translate_simple_select() -> None:
    sql = translate("SELECT 1", FakeCatalog({}))
    assert sql.strip().lower().startswith("select 1")


def test_translate_three_part_name_to_quoted_schema() -> None:
    sql = translate("SELECT * FROM `my-proj.my_ds.users`", FakeCatalog({}))
    assert '"my-proj:my_ds"."users"' in sql


def test_translate_three_part_dotted_unquoted() -> None:
    sql = translate("SELECT * FROM my-proj.my_ds.users", FakeCatalog({}))
    assert '"my-proj:my_ds"."users"' in sql


def test_translate_safe_prefix_to_try() -> None:
    sql = translate("SELECT SAFE.PARSE_DATE('%F','x')", FakeCatalog({}))
    assert "TRY(" in sql.upper()


def test_translate_wildcard_expands_to_union() -> None:
    catalog = FakeCatalog({("p", "d"): ["events_2024_01", "events_2024_02", "users"]})
    sql = translate("SELECT * FROM `p.d.events_*`", catalog)
    assert "events_2024_01" in sql
    assert "events_2024_02" in sql
    assert "users" not in sql
    assert "UNION ALL" in sql.upper()


def test_translate_rejects_legacy_sql_marker() -> None:
    with pytest.raises(UnsupportedSql):
        translate("#legacySQL\nSELECT 1", FakeCatalog({}))


def test_translate_rejects_ml_function() -> None:
    with pytest.raises(UnsupportedSql, match="ML"):
        translate("SELECT * FROM ML.PREDICT(MODEL `m`, TABLE `t`)", FakeCatalog({}))


def test_translate_rejects_st_function() -> None:
    with pytest.raises(UnsupportedSql, match="ST_"):
        translate("SELECT ST_GEOGFROMTEXT('POINT(1 1)')", FakeCatalog({}))


def test_translate_strips_partitioning_clause_in_create_table() -> None:
    sql = translate(
        "CREATE TABLE `p.d.t` (id INT64) PARTITION BY DATE(ts) OPTIONS()",
        FakeCatalog({}),
    )
    assert "PARTITION BY" not in sql.upper()
```

- [ ] **Step 2: Write the failing test for INFORMATION_SCHEMA**

`tests/unit/services/bigquery/test_info_schema.py`:

```python
import pytest

from gcp_local.services.bigquery.engine.info_schema import (
    UnsupportedInfoSchemaView,
    rewrite_info_schema_reference,
)


def test_tables_view_rewrites_to_catalog_select() -> None:
    out = rewrite_info_schema_reference("p", "d", "TABLES")
    assert "_gcp_local_meta.tables" in out
    assert "project = 'p'" in out
    assert "dataset_id = 'd'" in out


def test_columns_view_unnests_schema_json() -> None:
    out = rewrite_info_schema_reference("p", "d", "COLUMNS")
    assert "_gcp_local_meta.tables" in out
    assert "ordinal_position" in out


def test_schemata_view() -> None:
    out = rewrite_info_schema_reference("p", "d", "SCHEMATA")
    assert "_gcp_local_meta.datasets" in out


def test_unsupported_view_raises() -> None:
    with pytest.raises(UnsupportedInfoSchemaView):
        rewrite_info_schema_reference("p", "d", "JOBS_BY_USER")
```

- [ ] **Step 3: Implement `src/gcp_local/services/bigquery/engine/info_schema.py`**

```python
"""Rewrite BQ INFORMATION_SCHEMA references to selects over our catalog."""


_SUPPORTED = {"TABLES", "COLUMNS", "SCHEMATA"}


class UnsupportedInfoSchemaView(ValueError):
    """Raised for INFORMATION_SCHEMA views we don't expose in v1."""


_TABLES_SQL = (
    "SELECT "
    "  json_extract_string(record, '$.project') AS table_catalog, "
    "  json_extract_string(record, '$.dataset_id') AS table_schema, "
    "  json_extract_string(record, '$.table_id') AS table_name, "
    "  'BASE TABLE' AS table_type, "
    "  json_extract_string(record, '$.create_time') AS creation_time "
    "FROM _gcp_local_meta.tables "
    "WHERE project = '{project}' AND dataset_id = '{dataset}'"
)

_COLUMNS_SQL = (
    "WITH t AS ( "
    "  SELECT project, dataset_id, table_id, "
    "         json_extract(record, '$.schema') AS schema_json "
    "  FROM _gcp_local_meta.tables "
    "  WHERE project = '{project}' AND dataset_id = '{dataset}' "
    ") "
    "SELECT t.project AS table_catalog, t.dataset_id AS table_schema, "
    "       t.table_id AS table_name, "
    "       json_extract_string(f.value, '$.name') AS column_name, "
    "       (f.idx + 1) AS ordinal_position, "
    "       CASE WHEN json_extract_string(f.value, '$.mode') = 'REQUIRED' "
    "            THEN 'NO' ELSE 'YES' END AS is_nullable, "
    "       json_extract_string(f.value, '$.type') AS data_type "
    "FROM t, LATERAL UNNEST(json_extract(t.schema_json, '$[*]')) "
    "  WITH ORDINALITY AS f(value, idx)"
)

_SCHEMATA_SQL = (
    "SELECT "
    "  json_extract_string(record, '$.project') AS catalog_name, "
    "  json_extract_string(record, '$.dataset_id') AS schema_name, "
    "  json_extract_string(record, '$.location') AS location, "
    "  json_extract_string(record, '$.create_time') AS creation_time "
    "FROM _gcp_local_meta.datasets "
    "WHERE project = '{project}' AND dataset_id = '{dataset}'"
)


def rewrite_info_schema_reference(project: str, dataset: str, view: str) -> str:
    """Return a DuckDB SELECT that emulates `<dataset>.INFORMATION_SCHEMA.<view>`."""
    view_upper = view.upper()
    if view_upper not in _SUPPORTED:
        raise UnsupportedInfoSchemaView(
            f"INFORMATION_SCHEMA view {view!r} is not supported in gcp-local v1"
        )
    template = {
        "TABLES": _TABLES_SQL,
        "COLUMNS": _COLUMNS_SQL,
        "SCHEMATA": _SCHEMATA_SQL,
    }[view_upper]
    return f"({template.format(project=project, dataset=dataset)})"
```

- [ ] **Step 4: Implement `src/gcp_local/services/bigquery/engine/translate.py`**

```python
"""sqlglot-driven BigQuery → DuckDB translation pipeline (spec §6.2, §9)."""

import re
from typing import Protocol

import sqlglot
from sqlglot import exp

from gcp_local.services.bigquery.engine.info_schema import (
    UnsupportedInfoSchemaView,
    rewrite_info_schema_reference,
)


class CatalogLookup(Protocol):
    def list_table_ids(self, project: str, dataset_id: str) -> list[str]: ...


class UnsupportedSql(ValueError):
    """Raised for SQL features rejected in v1 (legacy SQL, ML.*, ST_*, scripting)."""


_LEGACY_MARKERS = re.compile(r"^\s*#legacySQL\b", re.IGNORECASE)


def translate(sql: str, catalog: CatalogLookup) -> str:
    if _LEGACY_MARKERS.match(sql):
        raise UnsupportedSql("legacy SQL is not supported (use standard SQL)")
    _reject_unsupported_functions(sql)
    tree = sqlglot.parse_one(sql, read="bigquery")
    tree = _rewrite_info_schema(tree)
    tree = _expand_wildcards(tree, catalog)
    tree = _rewrite_three_part_names(tree)
    tree = _rewrite_safe_prefix(tree)
    tree = _strip_partitioning(tree)
    return tree.sql(dialect="duckdb")


_BANNED = re.compile(
    r"\b(ML\.[A-Z_]+|ST_[A-Z_]+|DECLARE\s|BEGIN\s|EXCEPTION\s|FOR\s+SYSTEM_TIME\s+AS\s+OF)\b",
    re.IGNORECASE,
)


def _reject_unsupported_functions(sql: str) -> None:
    m = _BANNED.search(sql)
    if m:
        raise UnsupportedSql(f"unsupported feature in v1: {m.group(0).strip()}")


def _rewrite_three_part_names(tree: exp.Expression) -> exp.Expression:
    for tbl in tree.find_all(exp.Table):
        catalog = tbl.args.get("catalog")
        db = tbl.args.get("db")
        name = tbl.this
        if catalog is not None and db is not None and name is not None:
            project = catalog.name if isinstance(catalog, exp.Identifier) else str(catalog)
            dataset = db.name if isinstance(db, exp.Identifier) else str(db)
            schema_name = f"{project}:{dataset}"
            tbl.set("catalog", None)
            tbl.set("db", exp.to_identifier(schema_name, quoted=True))
            if isinstance(name, exp.Identifier):
                name.set("quoted", True)
    return tree


def _rewrite_safe_prefix(tree: exp.Expression) -> exp.Expression:
    # BigQuery's `SAFE.<fn>(...)` becomes `<fn>(...)` wrapped in DuckDB's TRY(...).
    for fn in list(tree.find_all(exp.Anonymous)):
        name = fn.name or ""
        if name.upper().startswith("SAFE."):
            inner_name = name.split(".", 1)[1]
            inner = exp.Anonymous(this=inner_name, expressions=fn.expressions)
            wrapped = exp.Anonymous(this="TRY", expressions=[inner])
            fn.replace(wrapped)
    return tree


def _expand_wildcards(
    tree: exp.Expression, catalog: CatalogLookup
) -> exp.Expression:
    for tbl in list(tree.find_all(exp.Table)):
        name_node = tbl.this
        if not isinstance(name_node, exp.Identifier):
            continue
        if not name_node.name.endswith("*"):
            continue
        catalog_node = tbl.args.get("catalog")
        db_node = tbl.args.get("db")
        if catalog_node is None or db_node is None:
            continue
        project = catalog_node.name if isinstance(catalog_node, exp.Identifier) else str(catalog_node)
        dataset = db_node.name if isinstance(db_node, exp.Identifier) else str(db_node)
        prefix = name_node.name.rstrip("*")
        ids = [t for t in catalog.list_table_ids(project, dataset) if t.startswith(prefix)]
        if not ids:
            continue
        sub_sql = " UNION ALL ".join(
            f'SELECT * FROM "{project}:{dataset}"."{tid}"' for tid in ids
        )
        sub = sqlglot.parse_one(f"({sub_sql})", read="duckdb")
        sub = exp.Subquery(this=sub, alias=tbl.args.get("alias"))
        tbl.replace(sub)
    return tree


def _rewrite_info_schema(tree: exp.Expression) -> exp.Expression:
    for tbl in list(tree.find_all(exp.Table)):
        # BQ writes `<dataset>.INFORMATION_SCHEMA.<VIEW>`; sqlglot may parse
        # `INFORMATION_SCHEMA` as a `db` and the view as `name`, with the
        # dataset in `catalog`.
        name = tbl.this.name if isinstance(tbl.this, exp.Identifier) else None
        db = tbl.args.get("db")
        catalog = tbl.args.get("catalog")
        if (
            name
            and db is not None
            and isinstance(db, exp.Identifier)
            and db.name.upper() == "INFORMATION_SCHEMA"
        ):
            dataset = catalog.name if isinstance(catalog, exp.Identifier) else None
            project = "_unknown"
            # If the user passed `project.dataset.INFORMATION_SCHEMA.VIEW`
            # sqlglot puts project in a 4th position; we don't have one here.
            # The route layer always rewrites bare references with the project
            # via a `defaultProject` wrap before calling translate(); we trust
            # `dataset` to be populated.
            if dataset is None:
                continue
            try:
                rewritten = rewrite_info_schema_reference(project, dataset, name)
            except UnsupportedInfoSchemaView as e:
                raise UnsupportedSql(str(e)) from None
            sub = sqlglot.parse_one(rewritten, read="duckdb")
            tbl.replace(exp.Subquery(this=sub, alias=tbl.args.get("alias")))
    return tree


def _strip_partitioning(tree: exp.Expression) -> exp.Expression:
    for create in tree.find_all(exp.Create):
        props = create.args.get("properties")
        if props is None:
            continue
        kept = [
            p for p in props.expressions
            if not isinstance(p, exp.PartitionedByProperty | exp.Cluster)
        ]
        props.set("expressions", kept)
    return tree
```

- [ ] **Step 5: Run translate + info_schema tests — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_translate.py tests/unit/services/bigquery/test_info_schema.py -v
```

(Some sqlglot details may need iteration — if a test fails, fix the AST traversal in `_rewrite_three_part_names` / `_expand_wildcards` rather than the test.)

- [ ] **Step 6: Quality gate + commit (sub-commit 9a)**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery/engine tests/unit/services/bigquery/test_translate.py tests/unit/services/bigquery/test_info_schema.py
git commit -m "$(cat <<'EOF'
feat(bigquery): SQL translation pipeline + INFORMATION_SCHEMA rewrite

sqlglot-driven BQ → DuckDB translation: three-part name rewrite,
wildcard table expansion, SAFE. → TRY(), INFORMATION_SCHEMA →
catalog selects, partitioning DDL strip. Rejects legacy SQL,
ML.*, ST_*, scripting, and time-travel syntax.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Sub-commit 9b: function shims registered on the connection

- [ ] **Step 7: Write the failing test for shims**

`tests/unit/services/bigquery/test_shims.py`:

```python
import re

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.shims import register_shims


@pytest.mark.asyncio
async def test_generate_uuid_returns_uuid_string() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    register_shims(conn)
    rows = await conn.execute("SELECT generate_uuid()")
    assert re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        rows[0][0],
    )


@pytest.mark.asyncio
async def test_format_date_basic_token() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    register_shims(conn)
    rows = await conn.execute("SELECT bq_format_date('%Y-%m-%d', DATE '2026-04-25')")
    assert rows[0][0] == "2026-04-25"


@pytest.mark.asyncio
async def test_parse_date_basic_token() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    register_shims(conn)
    rows = await conn.execute("SELECT bq_parse_date('%Y-%m-%d', '2026-04-25')")
    assert str(rows[0][0]) == "2026-04-25"


@pytest.mark.asyncio
async def test_format_timestamp_with_zone() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    register_shims(conn)
    rows = await conn.execute(
        "SELECT bq_format_timestamp('%Y-%m-%d %H:%M:%S', "
        "TIMESTAMP '2026-04-25 12:00:00+00')"
    )
    assert rows[0][0] == "2026-04-25 12:00:00"
```

- [ ] **Step 8: Implement `src/gcp_local/services/bigquery/engine/shims.py`**

```python
"""BigQuery scalar UDFs registered on the DuckDB connection (spec §9.2).

We name the functions with a `bq_` prefix and expose them as Python UDFs.
The translate() layer rewrites `FORMAT_DATE(...)` / `PARSE_DATE(...)` /
`FORMAT_TIMESTAMP(...)` / `PARSE_TIMESTAMP(...)` calls to `bq_<name>(...)`.
GENERATE_UUID() is rewritten to generate_uuid(); we register that name too.
"""

import datetime as dt
import uuid

from gcp_local.services.bigquery.engine.connection import BigQueryConnection


_BQ_TO_STRFTIME = {
    "%Y": "%Y", "%y": "%y", "%m": "%m", "%d": "%d",
    "%H": "%H", "%M": "%M", "%S": "%S", "%j": "%j",
    "%a": "%a", "%A": "%A", "%b": "%b", "%B": "%B",
    "%p": "%p", "%z": "%z", "%F": "%Y-%m-%d", "%T": "%H:%M:%S",
    "%f": "%f",
}


def _translate_format(fmt: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(fmt):
        if fmt[i] == "%" and i + 1 < len(fmt):
            token = fmt[i : i + 2]
            if token not in _BQ_TO_STRFTIME:
                raise ValueError(f"unsupported BQ format token: {token}")
            out.append(_BQ_TO_STRFTIME[token])
            i += 2
        else:
            out.append(fmt[i])
            i += 1
    return "".join(out)


def _generate_uuid() -> str:
    return str(uuid.uuid4())


def _bq_format_date(fmt: str, value: dt.date) -> str:
    return value.strftime(_translate_format(fmt))


def _bq_parse_date(fmt: str, value: str) -> dt.date:
    return dt.datetime.strptime(value, _translate_format(fmt)).date()


def _bq_format_timestamp(fmt: str, value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.strftime(_translate_format(fmt))


def _bq_parse_timestamp(fmt: str, value: str) -> dt.datetime:
    parsed = dt.datetime.strptime(value, _translate_format(fmt))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def register_shims(conn: BigQueryConnection) -> None:
    raw = conn._conn  # type: ignore[attr-defined]
    assert raw is not None
    raw.create_function("generate_uuid", _generate_uuid, [], "VARCHAR")
    raw.create_function(
        "bq_format_date", _bq_format_date, ["VARCHAR", "DATE"], "VARCHAR"
    )
    raw.create_function(
        "bq_parse_date", _bq_parse_date, ["VARCHAR", "VARCHAR"], "DATE"
    )
    raw.create_function(
        "bq_format_timestamp",
        _bq_format_timestamp,
        ["VARCHAR", "TIMESTAMP WITH TIME ZONE"],
        "VARCHAR",
    )
    raw.create_function(
        "bq_parse_timestamp",
        _bq_parse_timestamp,
        ["VARCHAR", "VARCHAR"],
        "TIMESTAMP WITH TIME ZONE",
    )
```

- [ ] **Step 9: Wire `register_shims` into the connection bootstrap**

In `src/gcp_local/services/bigquery/engine/connection.py`, after the catalog DDL loop in `startup()`, append:

```python
        # Avoid a circular import.
        from gcp_local.services.bigquery.engine.shims import register_shims
        register_shims(self)
```

- [ ] **Step 10: Run shims tests — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_shims.py -v
```

- [ ] **Step 11: Quality gate + commit (sub-commit 9b)**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery/engine/shims.py src/gcp_local/services/bigquery/engine/connection.py tests/unit/services/bigquery/test_shims.py
git commit -m "$(cat <<'EOF'
feat(bigquery): function shims (UUID / FORMAT_DATE / PARSE_DATE / TIMESTAMP)

Registers BQ-only scalar UDFs on the DuckDB connection so the
translate() layer can rewrite FORMAT_DATE/PARSE_DATE/FORMAT_TIMESTAMP/
PARSE_TIMESTAMP/GENERATE_UUID calls onto Python implementations.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: JobRunner + jobs REST routes

Goal: `engine/jobs.py` runs queries synchronously (per spec §6.1), materializes SELECT results into temp tables in `_gcp_local_jobs`, builds `JobRecord`s with `errorResult` populated on failure, and offers paged result reads. Then `routes/jobs.py` exposes `jobs.insert`, `jobs.get`, `jobs.list`, `jobs.cancel`, `jobs.query`, and `jobs.getQueryResults`. A 1-hour TTL sweeper task evicts old jobs.

**Files:**
- Create: `src/gcp_local/services/bigquery/engine/jobs.py`
- Create: `src/gcp_local/services/bigquery/routes/jobs.py`
- Modify: `src/gcp_local/services/bigquery/app.py` (include jobs router)
- Modify: `src/gcp_local/services/bigquery/service.py` (start/stop sweeper)
- Create: `tests/unit/services/bigquery/test_jobs.py`
- Create: `tests/unit/services/bigquery/test_routes_jobs.py`

### Sub-commit 10a: JobRunner

- [ ] **Step 1: Write the failing test for JobRunner**

`tests/unit/services/bigquery/test_jobs.py`:

```python
import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def runner() -> JobRunner:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    await storage.create_dataset(
        DatasetRecord(
            project="p",
            dataset_id="d",
            create_time="now",
            last_modified_time="now",
            description=None,
            labels={},
            location="US",
            default_table_expiration_ms=None,
        )
    )
    await storage.create_table(
        TableRecord(
            project="p",
            dataset_id="d",
            table_id="t",
            schema=[
                FieldSchema(name="id", type="INT64", mode="REQUIRED", fields=None),
                FieldSchema(name="name", type="STRING", mode="NULLABLE", fields=None),
            ],
            create_time="now",
            last_modified_time="now",
            description=None,
            labels={},
            time_partitioning=None,
            range_partitioning=None,
            clustering=None,
        )
    )
    await conn.execute('INSERT INTO "p:d"."t" VALUES (1, \'a\'), (2, \'b\'), (3, \'c\')')
    return JobRunner(connection=conn, storage=storage)


@pytest.mark.asyncio
async def test_run_select_returns_done_job_with_total_rows(runner: JobRunner) -> None:
    rec = await runner.run_query(project="p", job_id="j1", sql="SELECT * FROM `p.d.t`")
    assert rec.state == "DONE"
    assert rec.statement_type == "SELECT"
    assert rec.total_rows == 3
    assert rec.error_result is None


@pytest.mark.asyncio
async def test_run_dml_records_affected_rows(runner: JobRunner) -> None:
    rec = await runner.run_query(
        project="p", job_id="j2", sql="UPDATE `p.d.t` SET name='x' WHERE id=1"
    )
    assert rec.state == "DONE"
    assert rec.statement_type == "UPDATE"


@pytest.mark.asyncio
async def test_run_select_paging(runner: JobRunner) -> None:
    rec = await runner.run_query(project="p", job_id="j3", sql="SELECT * FROM `p.d.t` ORDER BY id")
    page1 = await runner.read_page(rec.job_id, page_size=2, page_token=None)
    assert len(page1.rows) == 2
    assert page1.next_page_token is not None
    page2 = await runner.read_page(rec.job_id, page_size=2, page_token=page1.next_page_token)
    assert len(page2.rows) == 1
    assert page2.next_page_token is None


@pytest.mark.asyncio
async def test_run_select_with_parse_error_records_error_result(
    runner: JobRunner,
) -> None:
    rec = await runner.run_query(project="p", job_id="j4", sql="SELECT FROM where")
    assert rec.state == "DONE"
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalidQuery"


@pytest.mark.asyncio
async def test_run_select_unknown_table_records_not_found(
    runner: JobRunner,
) -> None:
    rec = await runner.run_query(project="p", job_id="j5", sql="SELECT * FROM `p.d.missing`")
    assert rec.error_result is not None
    assert rec.error_result["reason"] in ("notFound", "invalidQuery")


@pytest.mark.asyncio
async def test_get_and_list_jobs(runner: JobRunner) -> None:
    await runner.run_query(project="p", job_id="j1", sql="SELECT 1")
    await runner.run_query(project="p", job_id="j2", sql="SELECT 2")
    rec = await runner.get("p", "j1")
    assert rec.job_id == "j1"
    listing = await runner.list_jobs("p")
    assert {r.job_id for r in listing} == {"j1", "j2"}


@pytest.mark.asyncio
async def test_ttl_sweep_evicts_old_jobs(runner: JobRunner) -> None:
    rec = await runner.run_query(project="p", job_id="j1", sql="SELECT 1")
    runner.set_clock(lambda: 0)
    await runner.run_query(project="p", job_id="j2", sql="SELECT 2")
    runner.set_clock(lambda: 7200)  # 2h later
    await runner.sweep_expired(ttl_seconds=3600)
    listing = await runner.list_jobs("p")
    assert {r.job_id for r in listing} == {"j2"} or rec.job_id not in {r.job_id for r in listing}
```

- [ ] **Step 2: Implement `src/gcp_local/services/bigquery/engine/jobs.py`**

```python
"""Synchronous job execution + result paging (spec §6)."""

import asyncio
import base64
import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass

import sqlglot

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.translate import (
    UnsupportedSql,
    translate,
)
from gcp_local.services.bigquery.errors import InvalidQuery, JobNotFound
from gcp_local.services.bigquery.models import FieldSchema, JobRecord
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetNotFound,
    TableNotFound,
)


@dataclass
class JobPage:
    rows: list[tuple]
    schema: list[FieldSchema]
    next_page_token: str | None


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _encode_token(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _decode_token(token: str | None) -> int:
    if not token:
        return 0
    try:
        return int(base64.urlsafe_b64decode(token.encode("ascii")))
    except Exception as e:
        raise InvalidQuery(f"invalid pageToken: {token!r}") from e


class _CatalogAdapter:
    """Adapts BigQueryStorage to the CatalogLookup protocol."""

    def __init__(self, storage: BigQueryStorage) -> None:
        self._storage = storage

    def list_table_ids(self, project: str, dataset_id: str) -> list[str]:
        # Used during translate() for wildcard expansion. translate() runs
        # inside an async run_query, but list_table_ids is sync — fetch via a
        # quick blocking SQL call against the catalog.
        loop = asyncio.get_event_loop()
        coro = self._storage.list_tables(project, dataset_id)
        recs = loop.run_until_complete(coro) if not loop.is_running() else []
        return [r.table_id for r in recs]


class JobRunner:
    def __init__(self, connection: BigQueryConnection, storage: BigQueryStorage) -> None:
        self._conn = connection
        self._storage = storage
        self._jobs: dict[tuple[str, str], JobRecord] = {}
        self._job_ended_at: dict[tuple[str, str], float] = {}
        self._job_schemas: dict[str, list[FieldSchema]] = {}
        self._clock: Callable[[], float] = time.monotonic

    def set_clock(self, clock: Callable[[], float]) -> None:
        self._clock = clock

    async def run_query(
        self, project: str, job_id: str, sql: str
    ) -> JobRecord:
        start = _now_iso()
        statement_type = _statement_type(sql)
        try:
            translated = await self._translate(project, sql)
            if statement_type == "SELECT":
                rec = await self._materialize_select(project, job_id, sql, translated, start)
            else:
                rec = await self._run_dml(project, job_id, sql, translated, start, statement_type)
        except (UnsupportedSql, sqlglot.errors.ParseError, ValueError, InvalidQuery) as e:
            rec = self._failed_record(
                project, job_id, sql, start, statement_type, "invalidQuery", str(e)
            )
        except (DatasetNotFound, TableNotFound) as e:
            rec = self._failed_record(
                project, job_id, sql, start, statement_type, "notFound", str(e)
            )
        except Exception as e:
            rec = self._failed_record(
                project, job_id, sql, start, statement_type, "internalError", str(e)
            )
        self._jobs[(project, job_id)] = rec
        self._job_ended_at[(project, job_id)] = self._clock()
        return rec

    async def _translate(self, project: str, sql: str) -> str:
        ids_by_dataset: dict[str, list[str]] = {}
        # Pre-fetch wildcard candidates: not strictly necessary if no wildcard
        # in `sql`, but cheap and lets the AST pass run synchronously.

        class _Cat:
            def list_table_ids(self_inner, p: str, d: str) -> list[str]:
                key = f"{p}/{d}"
                if key in ids_by_dataset:
                    return ids_by_dataset[key]
                return []

        for line in [sql]:
            if "*`" in line or "*'" in line or "_*" in line:
                # Fan out: list every dataset referenced by `project.*` style.
                # For v1 we resolve only the project we were given.
                datasets = await self._storage.list_datasets(project)
                for d in datasets:
                    tables = await self._storage.list_tables(project, d.dataset_id)
                    ids_by_dataset[f"{project}/{d.dataset_id}"] = [
                        t.table_id for t in tables
                    ]
        return translate(sql, _Cat())

    async def _materialize_select(
        self,
        project: str,
        job_id: str,
        sql: str,
        translated: str,
        start: str,
    ) -> JobRecord:
        temp_qual = f'"_gcp_local_jobs"."_job_{job_id}"'
        await self._conn.execute(
            f"CREATE TABLE {temp_qual} AS {translated}"
        )
        rows = await self._conn.execute(f"SELECT count(*) FROM {temp_qual}")
        total = int(rows[0][0]) if rows else 0
        schema = await self._infer_schema(temp_qual)
        self._job_schemas[job_id] = schema
        end = _now_iso()
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="QUERY",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type="SELECT",
            sql=sql,
            destination_table=("_gcp_local", "_gcp_local_jobs", f"_job_{job_id}"),
            total_rows=total,
            total_bytes_processed=0,
            error_result=None,
            errors=[],
        )

    async def _run_dml(
        self,
        project: str,
        job_id: str,
        sql: str,
        translated: str,
        start: str,
        statement_type: str,
    ) -> JobRecord:
        await self._conn.execute(translated)
        end = _now_iso()
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="DML",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type=statement_type,
            sql=sql,
            destination_table=None,
            total_rows=0,
            total_bytes_processed=0,
            error_result=None,
            errors=[],
        )

    def _failed_record(
        self,
        project: str,
        job_id: str,
        sql: str,
        start: str,
        statement_type: str,
        reason: str,
        message: str,
    ) -> JobRecord:
        end = _now_iso()
        err = {"reason": reason, "message": message, "domain": "global"}
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="QUERY" if statement_type == "SELECT" else "DML",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type=statement_type,
            sql=sql,
            destination_table=None,
            total_rows=0,
            total_bytes_processed=0,
            error_result=err,
            errors=[err],
        )

    async def _infer_schema(self, qualname: str) -> list[FieldSchema]:
        rows = await self._conn.execute(f"DESCRIBE {qualname}")
        out: list[FieldSchema] = []
        for col_name, col_type, *_ in rows:
            out.append(
                FieldSchema(
                    name=col_name,
                    type=_duckdb_to_bq_type(col_type),
                    mode="NULLABLE",
                    fields=None,
                )
            )
        return out

    async def get(self, project: str, job_id: str) -> JobRecord:
        try:
            return self._jobs[(project, job_id)]
        except KeyError:
            raise JobNotFound(f"{project}:{job_id}") from None

    async def list_jobs(self, project: str) -> list[JobRecord]:
        return [r for (p, _j), r in self._jobs.items() if p == project]

    async def cancel(self, project: str, job_id: str) -> JobRecord:
        return await self.get(project, job_id)

    async def read_page(
        self, job_id: str, *, page_size: int, page_token: str | None
    ) -> JobPage:
        offset = _decode_token(page_token)
        schema = self._job_schemas.get(job_id, [])
        rows = await self._conn.execute(
            f'SELECT * FROM "_gcp_local_jobs"."_job_{job_id}" LIMIT ? OFFSET ?',
            [page_size, offset],
        )
        next_off = offset + len(rows)
        # Determine total rows via count to know whether to emit a token.
        total_rows_q = await self._conn.execute(
            f'SELECT count(*) FROM "_gcp_local_jobs"."_job_{job_id}"'
        )
        total = int(total_rows_q[0][0]) if total_rows_q else 0
        return JobPage(
            rows=list(rows),
            schema=schema,
            next_page_token=_encode_token(next_off) if next_off < total else None,
        )

    async def sweep_expired(self, ttl_seconds: float) -> None:
        now = self._clock()
        expired = [
            key for key, ended in self._job_ended_at.items()
            if now - ended > ttl_seconds
        ]
        for key in expired:
            project, job_id = key
            await self._conn.execute(
                f'DROP TABLE IF EXISTS "_gcp_local_jobs"."_job_{job_id}"'
            )
            self._jobs.pop(key, None)
            self._job_ended_at.pop(key, None)
            self._job_schemas.pop(job_id, None)


def _statement_type(sql: str) -> str:
    head = sql.lstrip().split(None, 1)[0].upper()
    if head in {"INSERT", "UPDATE", "DELETE", "MERGE"}:
        return head
    return "SELECT"


_DUCKDB_TO_BQ = {
    "VARCHAR": "STRING",
    "BLOB": "BYTES",
    "BIGINT": "INT64",
    "INTEGER": "INT64",
    "DOUBLE": "FLOAT64",
    "BOOLEAN": "BOOL",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP WITH TIME ZONE": "TIMESTAMP",
    "TIMESTAMP": "DATETIME",
    "JSON": "JSON",
}


def _duckdb_to_bq_type(duckdb_type: str) -> str:
    base = duckdb_type.upper().split("(", 1)[0].strip()
    return _DUCKDB_TO_BQ.get(base, "STRING")
```

- [ ] **Step 3: Run JobRunner tests — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery/test_jobs.py -v
```

(The `_translate` method is conservative — it pre-fetches dataset/table names only when wildcards are detected; tests in this file don't exercise wildcards, so the bare path is fine.)

- [ ] **Step 4: Quality gate + commit (sub-commit 10a)**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery/engine/jobs.py tests/unit/services/bigquery/test_jobs.py
git commit -m "$(cat <<'EOF'
feat(bigquery): JobRunner — synchronous query execution + paging

Runs translated SQL synchronously, materializes SELECT results
into _gcp_local_jobs._job_<id> temp tables, captures errorResult
on failure, and pages results via base64'd LIMIT/OFFSET tokens.
TTL sweeper evicts records older than the configured horizon.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Sub-commit 10b: jobs REST routes + sweeper task

- [ ] **Step 5: Write the failing test for jobs routes**

`tests/unit/services/bigquery/test_routes_jobs.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> TestClient:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    c = TestClient(build_app(storage=storage, runner=runner))
    c.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    c.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                    {"name": "name", "type": "STRING"},
                ]
            },
        },
    )
    return c


def _seed_rows(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/t/insertAll",
        json={"rows": [{"json": {"id": i, "name": f"n{i}"}} for i in range(1, 4)]},
    ) if False else None  # placeholder; insertAll lands in Task 11.
    # Instead, use jobs.query to INSERT.
    client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "INSERT INTO `p.d.t` VALUES (1,'a'),(2,'b'),(3,'c')"},
    )


def test_jobs_query_synchronous(client: TestClient) -> None:
    _seed_rows(client)
    r = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT id, name FROM `p.d.t` ORDER BY id"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "bigquery#queryResponse"
    assert body["jobComplete"] is True
    assert body["totalRows"] == "3"
    rows = body["rows"]
    assert [r["f"][0]["v"] for r in rows] == ["1", "2", "3"]


def test_jobs_insert_async_shape(client: TestClient) -> None:
    _seed_rows(client)
    r = client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "j1"},
            "configuration": {"query": {"query": "SELECT id FROM `p.d.t`"}},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"]["state"] == "DONE"
    assert body["jobReference"] == {"projectId": "p", "jobId": "j1"}


def test_jobs_get_query_results_paging(client: TestClient) -> None:
    _seed_rows(client)
    r = client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "j2"},
            "configuration": {"query": {"query": "SELECT id FROM `p.d.t` ORDER BY id"}},
        },
    )
    assert r.status_code == 200
    page1 = client.get(
        "/bigquery/v2/projects/p/queries/j2", params={"maxResults": 2}
    ).json()
    assert len(page1["rows"]) == 2
    page2 = client.get(
        "/bigquery/v2/projects/p/queries/j2",
        params={"maxResults": 2, "pageToken": page1["pageToken"]},
    ).json()
    assert len(page2["rows"]) == 1


def test_jobs_query_parse_error_returns_error_result(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT FROM where"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["jobComplete"] is True
    assert body["errors"][0]["reason"] == "invalidQuery"


def test_jobs_get_returns_known_job(client: TestClient) -> None:
    _seed_rows(client)
    client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "jX"},
            "configuration": {"query": {"query": "SELECT 1"}},
        },
    )
    r = client.get("/bigquery/v2/projects/p/jobs/jX")
    assert r.status_code == 200
    assert r.json()["jobReference"]["jobId"] == "jX"
```

- [ ] **Step 6: Implement `src/gcp_local/services/bigquery/routes/jobs.py`**

```python
"""REST handlers for /bigquery/v2/projects/{p}/{jobs,queries}/*."""

import uuid
from typing import Any

from fastapi import APIRouter, Body, Path

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.errors import JobNotFound, bigquery_error_response
from gcp_local.services.bigquery.models import FieldSchema, JobRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_job_id,
    validate_project_id,
)
from gcp_local.services.bigquery.types import duckdb_value_to_bq_wire


def _job_to_api(rec: JobRecord) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "bigquery#job",
        "id": f"{rec.project}:{rec.job_id}",
        "jobReference": {"projectId": rec.project, "jobId": rec.job_id},
        "user_email": rec.user_email,
        "configuration": {"query": {"query": rec.sql}, "jobType": rec.job_type},
        "status": {"state": rec.state},
        "statistics": {
            "startTime": rec.start_time,
            "endTime": rec.end_time,
            "creationTime": rec.create_time,
            "totalBytesProcessed": str(rec.total_bytes_processed),
            "query": {
                "totalBytesProcessed": str(rec.total_bytes_processed),
                "statementType": rec.statement_type,
            },
        },
    }
    if rec.error_result is not None:
        body["status"]["errorResult"] = rec.error_result
        body["status"]["errors"] = rec.errors
    if rec.destination_table is not None:
        body["configuration"]["query"]["destinationTable"] = {
            "projectId": rec.destination_table[0],
            "datasetId": rec.destination_table[1],
            "tableId": rec.destination_table[2],
        }
    return body


def _rows_to_wire(
    rows: list[tuple], schema: list[FieldSchema]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        cells = [duckdb_value_to_bq_wire(v, schema[i]) for i, v in enumerate(row)]
        out.append({"f": cells})
    return out


def _schema_to_api(schema: list[FieldSchema]) -> dict[str, Any]:
    return {
        "fields": [
            {"name": f.name, "type": f.type, "mode": f.mode}
            for f in schema
        ]
    }


def build_router(runner: JobRunner) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post("/{project}/jobs")
    async def insert_job(project: str, body: dict[str, Any] = Body(...)) -> Any:
        try:
            validate_project_id(project)
            ref = body.get("jobReference") or {}
            job_id = ref.get("jobId") or f"job_{uuid.uuid4().hex}"
            validate_job_id(job_id)
            qcfg = (body.get("configuration") or {}).get("query") or {}
            sql = qcfg.get("query") or ""
            rec = await runner.run_query(project=project, job_id=job_id, sql=sql)
            return _job_to_api(rec)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/jobs/{job_id}")
    async def get_job(project: str, job_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.get(project, job_id)
            return _job_to_api(rec)
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/jobs")
    async def list_jobs(project: str) -> Any:
        try:
            validate_project_id(project)
            recs = await runner.list_jobs(project)
            return {
                "kind": "bigquery#jobList",
                "jobs": [_job_to_api(r) for r in recs],
            }
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.post("/{project}/jobs/{job_id}/cancel")
    async def cancel_job(project: str, job_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.cancel(project, job_id)
            return {"kind": "bigquery#jobCancelResponse", "job": _job_to_api(rec)}
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.post("/{project}/queries")
    async def query_sync(project: str, body: dict[str, Any] = Body(...)) -> Any:
        try:
            validate_project_id(project)
            sql = body.get("query") or ""
            page_size = int(body.get("maxResults") or 10000)
            job_id = body.get("requestId") or f"job_{uuid.uuid4().hex}"
            validate_job_id(job_id)
            rec = await runner.run_query(project=project, job_id=job_id, sql=sql)
            payload: dict[str, Any] = {
                "kind": "bigquery#queryResponse",
                "jobReference": {"projectId": project, "jobId": rec.job_id},
                "jobComplete": True,
                "totalRows": str(rec.total_rows),
                "totalBytesProcessed": "0",
            }
            if rec.error_result is not None:
                payload["errors"] = rec.errors
                payload["jobComplete"] = True
                return payload
            if rec.statement_type == "SELECT":
                page = await runner.read_page(rec.job_id, page_size=page_size, page_token=None)
                payload["schema"] = _schema_to_api(page.schema)
                payload["rows"] = _rows_to_wire(page.rows, page.schema)
                if page.next_page_token is not None:
                    payload["pageToken"] = page.next_page_token
            return payload
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/queries/{job_id}")
    async def get_query_results(
        project: str,
        job_id: str = Path(...),
        maxResults: int = 10000,
        pageToken: str | None = None,
    ) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.get(project, job_id)
            page = await runner.read_page(job_id, page_size=maxResults, page_token=pageToken)
            payload: dict[str, Any] = {
                "kind": "bigquery#getQueryResultsResponse",
                "jobReference": {"projectId": project, "jobId": job_id},
                "jobComplete": True,
                "totalRows": str(rec.total_rows),
                "schema": _schema_to_api(page.schema),
                "rows": _rows_to_wire(page.rows, page.schema),
            }
            if page.next_page_token is not None:
                payload["pageToken"] = page.next_page_token
            return payload
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    return router
```

- [ ] **Step 7: Update `app.py`** to take a `runner` and include the jobs router:

```python
from fastapi import FastAPI

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.routes.datasets import (
    build_router as datasets_router,
)
from gcp_local.services.bigquery.routes.jobs import (
    build_router as jobs_router,
)
from gcp_local.services.bigquery.routes.tables import (
    build_router as tables_router,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


def build_app(storage: BigQueryStorage, runner: JobRunner) -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    app.include_router(tables_router(storage))
    app.include_router(jobs_router(runner))
    return app
```

- [ ] **Step 8: Update `service.py`** to construct the runner, start a sweeper task, and pass both into `build_app`.

Replace the body of `start()`/`stop()` with:

```python
    async def start(self, ctx: Context) -> None:
        self._connection = self._make_connection(ctx)
        await self._connection.startup()
        self._storage = BigQueryStorage(self._connection)
        self._runner = JobRunner(connection=self._connection, storage=self._storage)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = build_app(storage=self._storage, runner=self._runner)
        self._server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(
            self._server.serve(), name=f"{self.name}-server"
        )
        self._sweeper_task = asyncio.create_task(
            self._sweeper_loop(), name=f"{self.name}-sweeper"
        )
        self._started = True
        log.info("bigquery service listening on :%d", port)

    async def _sweeper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(300)  # 5 minutes
                if self._runner is not None:
                    await self._runner.sweep_expired(ttl_seconds=3600)
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        for task in (self._server_task, self._sweeper_task):
            if task is not None:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (TimeoutError, asyncio.CancelledError):
                    pass
        if self._connection is not None:
            await self._connection.shutdown()
        self._started = False
```

Add the new attributes in `__init__`:

```python
        self._runner: JobRunner | None = None
        self._sweeper_task: asyncio.Task[None] | None = None
```

And add the import: `from gcp_local.services.bigquery.engine.jobs import JobRunner`.

- [ ] **Step 9: Run all bigquery tests — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery -v
```

- [ ] **Step 10: Quality gate + commit (sub-commit 10b)**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery tests/unit/services/bigquery
git commit -m "$(cat <<'EOF'
feat(bigquery): jobs REST routes + result-paging + TTL sweeper

Wires JobRunner into /bigquery/v2/projects/{p}/jobs (insert/get/
list/cancel) and /queries (sync + getQueryResults). Service starts
a background sweeper that evicts jobs older than 1 hour.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `tabledata.insertAll` (streaming inserts)

Goal: `/bigquery/v2/projects/{p}/datasets/{d}/tables/{t}/insertAll` route. Per-row JSON validation against the table's schema; valid rows are inserted in one batch. Table-not-found is request-level 404 (spec §7.1).

**Files:**
- Create: `src/gcp_local/services/bigquery/routes/tabledata.py`
- Modify: `src/gcp_local/services/bigquery/app.py` (include router)
- Create: `tests/unit/services/bigquery/test_routes_tabledata.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/services/bigquery/test_routes_tabledata.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> TestClient:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    c = TestClient(build_app(storage=storage, runner=runner))
    c.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    c.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                    {"name": "name", "type": "STRING"},
                ]
            },
        },
    )
    return c


def test_insert_all_happy_path(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/t/insertAll",
        json={
            "rows": [
                {"insertId": "x1", "json": {"id": 1, "name": "a"}},
                {"insertId": "x2", "json": {"id": 2, "name": "b"}},
            ]
        },
    )
    assert r.status_code == 200
    assert r.json() == {"kind": "bigquery#tableDataInsertAllResponse"}

    q = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT count(*) AS c FROM `p.d.t`"},
    ).json()
    assert q["rows"][0]["f"][0]["v"] == "2"


def test_insert_all_table_not_found_404(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/missing/insertAll",
        json={"rows": [{"json": {"id": 1, "name": "a"}}]},
    )
    assert r.status_code == 404
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


def test_insert_all_per_row_errors_when_skip_invalid_false(
    client: TestClient,
) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/t/insertAll",
        json={
            "skipInvalidRows": False,
            "rows": [
                {"json": {"id": 1, "name": "a"}},
                {"json": {"name": "missing-id"}},  # missing REQUIRED field
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "insertErrors" in body
    assert body["insertErrors"][0]["index"] == 1


def test_insert_all_skip_invalid_inserts_valid_rows(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/t/insertAll",
        json={
            "skipInvalidRows": True,
            "rows": [
                {"json": {"id": 1, "name": "a"}},
                {"json": {"name": "missing-id"}},
            ],
        },
    )
    assert r.status_code == 200
    q = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT count(*) AS c FROM `p.d.t`"},
    ).json()
    assert q["rows"][0]["f"][0]["v"] == "1"
```

- [ ] **Step 2: Implement `src/gcp_local/services/bigquery/routes/tabledata.py`**

```python
"""Streaming inserts: /bigquery/v2/projects/{p}/datasets/{d}/tables/{t}/insertAll."""

from typing import Any

from fastapi import APIRouter, Body

from gcp_local.services.bigquery.errors import bigquery_error_response
from gcp_local.services.bigquery.models import FieldSchema, TableRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    duckdb_table_qualname,
    validate_dataset_id,
    validate_project_id,
    validate_table_id,
)
from gcp_local.services.bigquery.storage import BigQueryStorage, TableNotFound


def _validate_row(payload: dict[str, Any], schema: list[FieldSchema]) -> list[str]:
    """Return a list of error messages for this row; empty list means valid."""
    errors: list[str] = []
    by_name = {f.name: f for f in schema}
    for f in schema:
        if f.mode == "REQUIRED" and payload.get(f.name) is None:
            errors.append(f"required field {f.name!r} is missing")
    for key in payload:
        if key not in by_name:
            errors.append(f"unknown field {key!r}")
    return errors


def _row_to_values(payload: dict[str, Any], schema: list[FieldSchema]) -> list[Any]:
    return [payload.get(f.name) for f in schema]


def build_router(storage: BigQueryStorage) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post(
        "/{project}/datasets/{dataset_id}/tables/{table_id}/insertAll"
    )
    async def insert_all(
        project: str,
        dataset_id: str,
        table_id: str,
        body: dict[str, Any] = Body(...),
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
            errs = _validate_row(payload, table.schema)
            if errs:
                insert_errors.append(
                    {
                        "index": i,
                        "errors": [
                            {"reason": "invalid", "message": e, "domain": "global"}
                            for e in errs
                        ],
                    }
                )
                continue
            valid_rows.append(_row_to_values(payload, table.schema))

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

- [ ] **Step 3: Update `app.py`** to include the tabledata router:

```python
from fastapi import FastAPI

from gcp_local.services.bigquery.engine.jobs import JobRunner
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
from gcp_local.services.bigquery.storage import BigQueryStorage


def build_app(storage: BigQueryStorage, runner: JobRunner) -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    app.include_router(tables_router(storage))
    app.include_router(jobs_router(runner))
    app.include_router(tabledata_router(storage))
    return app
```

- [ ] **Step 4: Run tests — pass**

```bash
. .venv/bin/activate && pytest tests/unit/services/bigquery -v
```

- [ ] **Step 5: Quality gate + commit**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add src/gcp_local/services/bigquery tests/unit/services/bigquery
git commit -m "$(cat <<'EOF'
feat(bigquery): tabledata.insertAll (streaming inserts)

Per-row JSON validation against the table's schema; surviving
rows go in via a single INSERT. Table-not-found is request-level
404. insertId is accepted and ignored (no dedup in v1).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Integration tests with real `google-cloud-bigquery`

Goal: a single integration-test file that drives the emulator end-to-end with the official client. Updates `tests/integration/conftest.py` to register the new service. Touches the core end-to-end test to assert `bigquery` shows up. Touches the docker test similarly.

**Files:**
- Modify: `tests/integration/conftest.py` (register BigQueryService, add `bigquery_port` to fixture)
- Modify: `tests/integration/test_core_end_to_end.py` (assert `bigquery` in `/services`)
- Modify: `tests/integration/test_docker_image.py` (assert bigquery boots with the all-services image)
- Create: `tests/integration/test_bigquery_integration.py`

- [ ] **Step 1: Update `tests/integration/conftest.py`**

Add the import and fixture changes:

```python
from gcp_local.services.bigquery import BigQueryService
```

In the body of `emulator()`:

```python
    registry.register("bigquery", BigQueryService)
    bigquery_port = _free_port()
    settings = Settings(
        services=["gcs", "secret_manager", "bigquery"],
        persist=False,
        data_dir=tmp_path,
        admin_port=admin_port,
        port_overrides={
            "gcs": gcs_port,
            "secret_manager": secret_manager_port,
            "bigquery": bigquery_port,
        },
    )
```

And in the `await _wait_for_port` block, also wait for `bigquery_port` and yield it under `"bigquery_port"`.

- [ ] **Step 2: Update `tests/integration/test_core_end_to_end.py`** to assert `"bigquery"` is in the listed services.

(Open the test, find the existing services-list assertion, and extend it to include `"bigquery"`.)

- [ ] **Step 3: Update `tests/integration/test_docker_image.py`** to assert the BQ port is reachable.

(Add a `httpx.get(f"http://127.0.0.1:{bq_port}/")` assertion mirroring the GCS one.)

- [ ] **Step 4: Write the integration test**

`tests/integration/test_bigquery_integration.py`:

```python
"""Drive the emulator with the real google-cloud-bigquery client."""

import os
from typing import Any

import pytest
from google.api_core import exceptions as gax_exceptions
from google.auth import credentials as ga_credentials
from google.cloud import bigquery
from google.cloud.bigquery import (
    DatasetReference,
    LoadJobConfig,
    SchemaField,
    Table,
    TableReference,
)


def _client(emulator: dict[str, int]) -> bigquery.Client:
    os.environ["BIGQUERY_EMULATOR_HOST"] = f"localhost:{emulator['bigquery_port']}"
    return bigquery.Client(
        project="test-project",
        credentials=ga_credentials.AnonymousCredentials(),
        client_options={
            "api_endpoint": f"http://localhost:{emulator['bigquery_port']}"
        },
    )


@pytest.mark.asyncio
async def test_dataset_crud(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ref = DatasetReference("test-project", "ds_crud")
    ds = bigquery.Dataset(ref)
    ds.labels = {"env": "dev"}
    client.create_dataset(ds)

    got = client.get_dataset(ref)
    assert got.labels == {"env": "dev"}

    got.description = "hello"
    client.update_dataset(got, ["description"])
    assert client.get_dataset(ref).description == "hello"

    client.delete_dataset(ref)
    with pytest.raises(gax_exceptions.NotFound):
        client.get_dataset(ref)


@pytest.mark.asyncio
async def test_table_crud_with_struct_array(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_t")))
    schema = [
        SchemaField("id", "INT64", mode="REQUIRED"),
        SchemaField("tags", "STRING", mode="REPEATED"),
        SchemaField(
            "addr",
            "RECORD",
            mode="NULLABLE",
            fields=[
                SchemaField("city", "STRING"),
                SchemaField("zip", "STRING", mode="REQUIRED"),
            ],
        ),
    ]
    table = bigquery.Table(
        TableReference(DatasetReference("test-project", "ds_t"), "tbl"),
        schema=schema,
    )
    client.create_table(table)
    got = client.get_table(table.reference)
    assert [f.name for f in got.schema] == ["id", "tags", "addr"]


@pytest.mark.asyncio
async def test_streaming_insert_then_query(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_si")))
    schema = [
        SchemaField("id", "INT64", mode="REQUIRED"),
        SchemaField("name", "STRING"),
    ]
    table = client.create_table(
        bigquery.Table(
            TableReference(DatasetReference("test-project", "ds_si"), "rows"),
            schema=schema,
        )
    )
    errors = client.insert_rows_json(
        table, [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    )
    assert errors == []
    rows = list(
        client.query("SELECT id, name FROM `test-project.ds_si.rows` ORDER BY id").result()
    )
    assert [(r["id"], r["name"]) for r in rows] == [(1, "a"), (2, "b")]


@pytest.mark.asyncio
async def test_dml_round_trip(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_dml")))
    schema = [SchemaField("id", "INT64", mode="REQUIRED")]
    table = client.create_table(
        bigquery.Table(
            TableReference(DatasetReference("test-project", "ds_dml"), "t"),
            schema=schema,
        )
    )
    client.query("INSERT INTO `test-project.ds_dml.t` VALUES (1),(2),(3)").result()
    client.query("UPDATE `test-project.ds_dml.t` SET id=99 WHERE id=2").result()
    client.query("DELETE FROM `test-project.ds_dml.t` WHERE id=3").result()
    rows = sorted(
        r["id"]
        for r in client.query("SELECT id FROM `test-project.ds_dml.t`").result()
    )
    assert rows == [1, 99]


@pytest.mark.asyncio
async def test_paging_with_max_results(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_pg")))
    schema = [SchemaField("id", "INT64", mode="REQUIRED")]
    table = client.create_table(
        bigquery.Table(
            TableReference(DatasetReference("test-project", "ds_pg"), "t"),
            schema=schema,
        )
    )
    client.insert_rows_json(table, [{"id": i} for i in range(10)])
    iterator = client.query(
        "SELECT id FROM `test-project.ds_pg.t` ORDER BY id"
    ).result(page_size=4)
    assert sorted(r["id"] for r in iterator) == list(range(10))


@pytest.mark.asyncio
async def test_query_unknown_table_raises_not_found(
    emulator: dict[str, int],
) -> None:
    client = _client(emulator)
    with pytest.raises((gax_exceptions.NotFound, gax_exceptions.BadRequest)):
        client.query("SELECT * FROM `test-project.no_such_ds.no_such_t`").result()


@pytest.mark.asyncio
async def test_query_parse_error_is_bad_request(
    emulator: dict[str, int],
) -> None:
    client = _client(emulator)
    with pytest.raises(gax_exceptions.BadRequest):
        client.query("SELECT FROM where").result()


@pytest.mark.asyncio
async def test_information_schema_tables(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_is")))
    client.create_table(
        bigquery.Table(
            TableReference(DatasetReference("test-project", "ds_is"), "alpha"),
            schema=[SchemaField("x", "INT64")],
        )
    )
    rows = list(
        client.query(
            "SELECT table_name FROM `test-project.ds_is.INFORMATION_SCHEMA.TABLES` "
            "ORDER BY table_name"
        ).result()
    )
    names = [r["table_name"] for r in rows]
    assert "alpha" in names


@pytest.mark.asyncio
async def test_jobs_list_includes_recent_job(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    client.query("SELECT 1").result()
    jobs = list(client.list_jobs(max_results=10))
    assert any(j.state == "DONE" for j in jobs)
```

- [ ] **Step 5: Run integration tests**

```bash
. .venv/bin/activate && pytest tests/integration/test_bigquery_integration.py -v
```

If the official client refuses to honor the emulator host for some endpoints, double-check the `BIGQUERY_EMULATOR_HOST` env var contract for the installed `google-cloud-bigquery` version (>=3.17 honors it). If a request 404s on a path the emulator doesn't recognize, surface the URL in the failure and add the route. Iterate until all 9 cases pass. Then run the full integration suite to make sure GCS + Secret Manager are still green:

```bash
. .venv/bin/activate && pytest tests/integration -v
```

- [ ] **Step 6: Quality gate + commit**

```bash
. .venv/bin/activate && ruff check . && ruff format --check . && mypy && pytest
git add tests/integration src/gcp_local/services/bigquery
git commit -m "$(cat <<'EOF'
test(bigquery): integration tests driving real google-cloud-bigquery client

Covers dataset/table CRUD with STRUCT+ARRAY, streaming-insert →
query round-trip, DML, multi-page result iteration,
INFORMATION_SCHEMA.TABLES, error paths (NotFound, BadRequest),
and jobs.list visibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin bigquery
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base master --head bigquery --title "feat(bigquery): emulator service (query, DML, streaming inserts)" --body "$(cat <<'EOF'
## Summary
- Implements the BigQuery service per the design at
  `docs/superpowers/specs/2026-04-25-gcp-local-bigquery-design.md`.
- DuckDB-backed query execution with sqlglot translation;
  catalog metadata in `_gcp_local_meta`; query result temp tables
  in `_gcp_local_jobs`. Synchronous-but-async-shaped jobs (TTL 1h).
- REST surface: `datasets.*`, `tables.*`, `jobs.{insert,get,list,
  cancel,query,getQueryResults}`, `tabledata.insertAll`.
- DML (INSERT/UPDATE/DELETE/MERGE) routed through the same
  translation pipeline. INFORMATION_SCHEMA.{TABLES, COLUMNS,
  SCHEMATA} resolved from the catalog at parse time.
- Lean type fidelity per spec: TIMESTAMP vs DATETIME documented;
  GEOGRAPHY/INTERVAL/RANGE rejected at schema-create.

## Test plan
- [ ] `pytest tests/unit/services/bigquery -v`
- [ ] `pytest tests/integration/test_bigquery_integration.py -v`
- [ ] `pytest tests/integration -v` (no GCS/Secret-Manager regressions)
- [ ] `ruff check . && ruff format --check . && mypy`
- [ ] `pytest tests/integration/test_docker_image.py` (image boot still green)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Hand off**

Print the PR URL to the user. Done.

