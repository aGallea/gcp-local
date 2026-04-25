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
