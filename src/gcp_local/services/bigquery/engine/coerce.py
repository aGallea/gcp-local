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
    """Return values in schema field order, coercing each via ``coerce_value``.

    Missing keys (fields absent from the payload) yield ``None``. The output is
    positional and ready to splice into a parameterized ``INSERT ... VALUES``.
    """
    return [coerce_value(payload.get(f.name), f) for f in schema]
