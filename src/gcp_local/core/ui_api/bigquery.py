"""ui-api BigQuery endpoints.

Thin presenter layer over ``BigQueryStorage`` and ``JobRunner``. Returns
UI-shaped responses (BQ-style field schemas, JSON-safe cell values, simple
preview/query payloads) rather than the full Google wire-format that the
public REST API on port 9050 emits.
"""

import base64
import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.errors import UiApiError
from gcp_local.services.bigquery.engine._time import now_epoch_ms_str
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.names import (
    InvalidName,
    duckdb_table_qualname,
    validate_dataset_id,
    validate_project_id,
    validate_table_id,
)
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetAlreadyExists,
    DatasetNotFound,
    TableNotFound,
)

# ---- Schemas ---------------------------------------------------------------


class FieldInfo(BaseModel):
    name: str
    type: str
    mode: str
    fields: list["FieldInfo"] | None = None


FieldInfo.model_rebuild()


class ProjectInfo(BaseModel):
    project: str
    dataset_count: int


class ProjectList(BaseModel):
    projects: list[ProjectInfo]


class DatasetSummary(BaseModel):
    project: str
    dataset_id: str
    location: str
    create_time: str
    last_modified_time: str


class DatasetList(BaseModel):
    datasets: list[DatasetSummary]


class CreateDatasetRequest(BaseModel):
    dataset_id: str
    location: str = "US"


class TableSummary(BaseModel):
    project: str
    dataset_id: str
    table_id: str
    create_time: str
    last_modified_time: str
    num_rows: int


class TableList(BaseModel):
    tables: list[TableSummary]


class TableMetadata(BaseModel):
    project: str
    dataset_id: str
    table_id: str
    table_schema: list[FieldInfo]
    create_time: str
    last_modified_time: str
    description: str | None = None
    num_rows: int


class TablePreview(BaseModel):
    table_schema: list[FieldInfo]
    rows: list[list[Any]]
    total_rows: int
    next_offset: int | None = None


class QueryRequest(BaseModel):
    project: str
    sql: str
    max_results: int = 100


class QueryResult(BaseModel):
    job_id: str
    statement_type: str
    table_schema: list[FieldInfo]
    rows: list[list[Any]]
    total_rows: int
    error: str | None = None


# ---- Conversions -----------------------------------------------------------


def _field_to_info(f: FieldSchema) -> FieldInfo:
    return FieldInfo(
        name=f.name,
        type=f.type,
        mode=f.mode,
        fields=[_field_to_info(s) for s in f.fields] if f.fields else None,
    )


def _cell_to_jsonable(value: Any) -> Any:
    """Convert a DuckDB cell value to a JSON-safe primitive for the UI."""
    if value is None:
        return None
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dt.datetime):
        # ISO-8601 keeps the timezone marker if present.
        return value.isoformat()
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_cell_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _cell_to_jsonable(v) for k, v in value.items()}
    return str(value)


# ---- Helpers ---------------------------------------------------------------


def _get_bq(lc: Lifecycle) -> tuple[BigQueryStorage, JobRunner]:
    for svc in lc.services:
        if svc.name == "bigquery":
            from gcp_local.services.bigquery.service import BigQueryService

            assert isinstance(svc, BigQueryService)
            return svc.storage, svc.runner
    raise UiApiError(
        status_code=503,
        code="service_unavailable",
        message="bigquery service is not running",
    )


def _bq_dep(request: Request) -> tuple[BigQueryStorage, JobRunner]:
    lc: Lifecycle = request.app.state.lifecycle
    return _get_bq(lc)


BqDep = Annotated[tuple[BigQueryStorage, JobRunner], Depends(_bq_dep)]


def _validate_path(
    *,
    project: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
) -> None:
    try:
        if project is not None:
            validate_project_id(project)
        if dataset_id is not None:
            validate_dataset_id(dataset_id)
        if table_id is not None:
            validate_table_id(table_id)
    except InvalidName as e:
        raise UiApiError(status_code=400, code="invalid_argument", message=str(e)) from None


def _dataset_to_summary(rec: DatasetRecord) -> DatasetSummary:
    return DatasetSummary(
        project=rec.project,
        dataset_id=rec.dataset_id,
        location=rec.location,
        create_time=rec.create_time,
        last_modified_time=rec.last_modified_time,
    )


def _table_to_summary(rec: TableRecord, num_rows: int) -> TableSummary:
    return TableSummary(
        project=rec.project,
        dataset_id=rec.dataset_id,
        table_id=rec.table_id,
        create_time=rec.create_time,
        last_modified_time=rec.last_modified_time,
        num_rows=num_rows,
    )


async def _count_rows(storage: BigQueryStorage, rec: TableRecord) -> int:
    qualname = duckdb_table_qualname(rec.project, rec.dataset_id, rec.table_id)
    rows = await storage.connection.execute(f"SELECT count(*) FROM {qualname}")
    return int(rows[0][0]) if rows else 0


# ---- Router ----------------------------------------------------------------


def build_bigquery_router() -> APIRouter:
    router = APIRouter(prefix="/bigquery", tags=["bigquery"])

    @router.get("/projects", response_model=ProjectList)
    async def list_projects(bq: BqDep) -> ProjectList:
        storage, _ = bq
        rows = await storage.connection.execute(
            "SELECT project, count(*) FROM _gcp_local_meta.datasets "
            "GROUP BY project ORDER BY project"
        )
        return ProjectList(
            projects=[ProjectInfo(project=str(r[0]), dataset_count=int(r[1])) for r in rows],
        )

    @router.get("/projects/{project}/datasets", response_model=DatasetList)
    async def list_datasets(project: str, bq: BqDep) -> DatasetList:
        _validate_path(project=project)
        storage, _ = bq
        records = await storage.list_datasets(project)
        return DatasetList(datasets=[_dataset_to_summary(r) for r in records])

    @router.post(
        "/projects/{project}/datasets",
        response_model=DatasetSummary,
        status_code=201,
    )
    async def create_dataset(
        project: str,
        payload: CreateDatasetRequest,
        bq: BqDep,
    ) -> DatasetSummary:
        _validate_path(project=project)
        if not payload.dataset_id.strip():
            raise UiApiError(
                status_code=400,
                code="invalid_argument",
                message="dataset_id must not be empty",
            )
        try:
            validate_dataset_id(payload.dataset_id)
        except InvalidName as e:
            raise UiApiError(status_code=400, code="invalid_argument", message=str(e)) from None
        storage, _ = bq
        now = now_epoch_ms_str()
        rec = DatasetRecord(
            project=project,
            dataset_id=payload.dataset_id,
            create_time=now,
            last_modified_time=now,
            description=None,
            labels={},
            location=payload.location or "US",
            default_table_expiration_ms=None,
        )
        try:
            await storage.create_dataset(rec)
        except DatasetAlreadyExists:
            raise UiApiError(
                status_code=409,
                code="already_exists",
                message=f"dataset '{project}:{payload.dataset_id}' already exists",
            ) from None
        return _dataset_to_summary(rec)

    @router.delete(
        "/projects/{project}/datasets/{dataset_id}",
        status_code=204,
    )
    async def delete_dataset(
        project: str,
        dataset_id: str,
        bq: BqDep,
        delete_contents: bool = Query(default=False),
    ) -> Response:
        _validate_path(project=project, dataset_id=dataset_id)
        storage, _ = bq
        try:
            await storage.delete_dataset(project, dataset_id, delete_contents=delete_contents)
        except DatasetNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"dataset '{project}:{dataset_id}' not found",
            ) from None
        except ValueError as e:
            # Storage raises ValueError when dataset has tables and delete_contents=False.
            raise UiApiError(
                status_code=409,
                code="not_empty",
                message=str(e) + "; pass delete_contents=true to drop tables too",
            ) from None
        return Response(status_code=204)

    @router.get(
        "/projects/{project}/datasets/{dataset_id}/tables",
        response_model=TableList,
    )
    async def list_tables(project: str, dataset_id: str, bq: BqDep) -> TableList:
        _validate_path(project=project, dataset_id=dataset_id)
        storage, _ = bq
        try:
            await storage.get_dataset(project, dataset_id)
        except DatasetNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"dataset '{project}:{dataset_id}' not found",
            ) from None
        records = await storage.list_tables(project, dataset_id)
        summaries = [
            _table_to_summary(r, await _count_rows(storage, r)) for r in records
        ]
        return TableList(tables=summaries)

    @router.get(
        "/projects/{project}/datasets/{dataset_id}/tables/{table_id}",
        response_model=TableMetadata,
    )
    async def get_table(
        project: str,
        dataset_id: str,
        table_id: str,
        bq: BqDep,
    ) -> TableMetadata:
        _validate_path(project=project, dataset_id=dataset_id, table_id=table_id)
        storage, _ = bq
        try:
            rec = await storage.get_table(project, dataset_id, table_id)
        except TableNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"table '{project}:{dataset_id}.{table_id}' not found",
            ) from None
        qualname = duckdb_table_qualname(project, dataset_id, table_id)
        rows = await storage.connection.execute(f"SELECT count(*) FROM {qualname}")
        num_rows = int(rows[0][0]) if rows else 0
        return TableMetadata(
            project=rec.project,
            dataset_id=rec.dataset_id,
            table_id=rec.table_id,
            table_schema=[_field_to_info(f) for f in rec.schema],
            create_time=rec.create_time,
            last_modified_time=rec.last_modified_time,
            description=rec.description,
            num_rows=num_rows,
        )

    @router.delete(
        "/projects/{project}/datasets/{dataset_id}/tables/{table_id}",
        status_code=204,
    )
    async def delete_table(
        project: str,
        dataset_id: str,
        table_id: str,
        bq: BqDep,
    ) -> Response:
        _validate_path(project=project, dataset_id=dataset_id, table_id=table_id)
        storage, _ = bq
        try:
            await storage.delete_table(project, dataset_id, table_id)
        except TableNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"table '{project}:{dataset_id}.{table_id}' not found",
            ) from None
        return Response(status_code=204)

    @router.get(
        "/projects/{project}/datasets/{dataset_id}/tables/{table_id}/preview",
        response_model=TablePreview,
    )
    async def preview_table(
        project: str,
        dataset_id: str,
        table_id: str,
        bq: BqDep,
        max_results: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> TablePreview:
        _validate_path(project=project, dataset_id=dataset_id, table_id=table_id)
        storage, _ = bq
        try:
            rec = await storage.get_table(project, dataset_id, table_id)
        except TableNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"table '{project}:{dataset_id}.{table_id}' not found",
            ) from None
        qualname = duckdb_table_qualname(project, dataset_id, table_id)
        count_rows = await storage.connection.execute(f"SELECT count(*) FROM {qualname}")
        total = int(count_rows[0][0]) if count_rows else 0
        data_rows = await storage.connection.execute(
            f"SELECT * FROM {qualname} LIMIT ? OFFSET ?",
            [max_results, offset],
        )
        out_rows = [[_cell_to_jsonable(c) for c in row] for row in data_rows]
        next_offset = offset + len(out_rows) if (offset + len(out_rows)) < total else None
        return TablePreview(
            table_schema=[_field_to_info(f) for f in rec.schema],
            rows=out_rows,
            total_rows=total,
            next_offset=next_offset,
        )

    @router.post("/queries", response_model=QueryResult)
    async def run_query(payload: QueryRequest, bq: BqDep) -> QueryResult:
        _validate_path(project=payload.project)
        if not payload.sql.strip():
            raise UiApiError(
                status_code=400,
                code="invalid_argument",
                message="sql must not be empty",
            )
        _, runner = bq
        job_id = f"ui-{uuid.uuid4().hex}"
        rec = await runner.run_query(payload.project, job_id, payload.sql)
        if rec.error_result is not None:
            return QueryResult(
                job_id=job_id,
                statement_type=rec.statement_type,
                table_schema=[],
                rows=[],
                total_rows=0,
                error=rec.error_result.get("message") or json.dumps(rec.error_result),
            )
        if rec.statement_type != "SELECT":
            return QueryResult(
                job_id=job_id,
                statement_type=rec.statement_type,
                table_schema=[],
                rows=[],
                total_rows=rec.total_rows,
                error=None,
            )
        page = await runner.read_page(job_id, page_size=payload.max_results, page_token=None)
        out_rows = [[_cell_to_jsonable(c) for c in row] for row in page.rows]
        return QueryResult(
            job_id=job_id,
            statement_type=rec.statement_type,
            table_schema=[_field_to_info(f) for f in page.schema],
            rows=out_rows,
            total_rows=rec.total_rows,
            error=None,
        )

    return router
