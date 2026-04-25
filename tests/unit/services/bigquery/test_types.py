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
    assert bq_field_to_duckdb_ddl(f) == '"addr" STRUCT("city" VARCHAR, "zip" VARCHAR)'


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
    assert bq_field_to_duckdb_ddl(b) == '"b" DECIMAL(38, 38)'


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
    assert schema_to_duckdb_columns(schema) == '"id" BIGINT NOT NULL, "name" VARCHAR'


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
    assert out["v"] == "1777118400.000000"


def test_wire_date_iso() -> None:
    f = FieldSchema(name="x", type="DATE", mode="NULLABLE", fields=None)
    assert duckdb_value_to_bq_wire(dt.date(2026, 4, 25), f) == {"v": "2026-04-25"}


def test_wire_repeated_string() -> None:
    f = FieldSchema(name="tags", type="STRING", mode="REPEATED", fields=None)
    assert duckdb_value_to_bq_wire(["a", "b"], f) == {"v": [{"v": "a"}, {"v": "b"}]}


def test_wire_struct() -> None:
    inner = [
        FieldSchema(name="city", type="STRING", mode="NULLABLE", fields=None),
        FieldSchema(name="zip", type="STRING", mode="REQUIRED", fields=None),
    ]
    f = FieldSchema(name="addr", type="RECORD", mode="NULLABLE", fields=inner)
    val = {"city": "NYC", "zip": "10001"}
    assert duckdb_value_to_bq_wire(val, f) == {"v": {"f": [{"v": "NYC"}, {"v": "10001"}]}}
