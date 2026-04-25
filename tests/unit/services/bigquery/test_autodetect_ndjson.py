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


def test_repeated_with_none_element() -> None:
    schema = autodetect_ndjson([{"tags": ["a", None, "b"]}])
    assert (schema[0].type, schema[0].mode) == ("STRING", "REPEATED")


def test_sparse_record_keys() -> None:
    schema = autodetect_ndjson(
        [{"a": {"x": 1}}, {"a": {"y": 2}}]
    )
    f = schema[0]
    assert f.type == "RECORD"
    assert f.fields is not None
    by_name = {sub.name: sub for sub in f.fields}
    assert by_name["x"].type == "INT64"
    assert by_name["y"].type == "INT64"
