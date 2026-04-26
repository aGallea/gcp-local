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
