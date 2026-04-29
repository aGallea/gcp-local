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
        return {"v": {"f": [duckdb_value_to_bq_wire(value[sub.name], sub) for sub in field.fields]}}
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
            # google-cloud-bigquery's CellDataParser parses TIMESTAMP cells via
            # `_datetime_from_microseconds(int(value))`, so the wire value must
            # be a string-encoded integer count of microseconds since epoch.
            # A float-seconds form (e.g. "1705322096.000000") makes int() raise.
            return str(round(ts.timestamp() * 1_000_000))
        case "DATETIME":
            return value.isoformat(sep="T", timespec="microseconds")
        case _:
            return str(value)
