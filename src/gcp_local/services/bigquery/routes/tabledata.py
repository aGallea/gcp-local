"""Streaming inserts: /bigquery/v2/projects/{p}/datasets/{d}/tables/{t}/insertAll."""

import json
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


def _coerce_value(value: Any, field: FieldSchema) -> Any:
    """Adapt one cell to a form DuckDB will accept for the column's type.

    Real BigQuery's `tabledata.insertAll` lets clients send a native dict / list
    for a `JSON` column; DuckDB's parameter binder doesn't auto-convert those, so
    we serialize to a JSON string here. REPEATED JSON columns are handled by
    serializing each element.
    """
    if value is None:
        return None
    if field.type == "JSON":
        if field.mode == "REPEATED":
            return [json.dumps(v) if isinstance(v, dict | list) else v for v in value]
        if isinstance(value, dict | list):
            return json.dumps(value)
    return value


def _row_to_values(payload: dict[str, Any], schema: list[FieldSchema]) -> list[Any]:
    return [_coerce_value(payload.get(f.name), f) for f in schema]


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
            errs = _validate_row(payload, table.schema)
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
