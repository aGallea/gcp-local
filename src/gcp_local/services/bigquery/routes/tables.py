"""REST handlers for /bigquery/v2/projects/{p}/datasets/{d}/tables/*."""

from typing import Any

from fastapi import APIRouter, Body, Response

from gcp_local.services.bigquery.engine._time import now_epoch_ms_str
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
        body: dict[str, Any] = Body(...),  # noqa: B008
    ) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            ref = body.get("tableReference") or {}
            table_id = ref.get("tableId") or ""
            validate_table_id(table_id)
            schema = parse_table_schema((body.get("schema") or {}).get("fields") or [])
            now = now_epoch_ms_str()
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
        "/{project}/datasets/{dataset_id}/tables/{table_id}",
        status_code=204,
        response_model=None,
    )
    async def delete_table(project: str, dataset_id: str, table_id: str) -> Response:
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
        body: dict[str, Any] = Body(...),  # noqa: B008
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
            rec.last_modified_time = now_epoch_ms_str()
            await storage.update_table(rec)
            return _to_api(rec)
        except (TableNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    return router
