"""CSV schema inference (spec §7.2)."""

import pytest

from gcp_local.services.bigquery.engine.autodetect import (
    AutodetectError,
    autodetect_csv,
)


def test_with_header_int_column() -> None:
    rows = [["id", "name"], ["1", "alice"], ["2", "bob"]]
    schema = autodetect_csv(rows, has_header=True)
    by_name = {f.name: f for f in schema}
    assert by_name["id"].type == "INT64"
    assert by_name["name"].type == "STRING"


def test_with_header_float_inferred_when_dot_present() -> None:
    rows = [["x"], ["1"], ["2.5"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "FLOAT64"


def test_with_header_bool_column() -> None:
    rows = [["flag"], ["true"], ["FALSE"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "BOOL"


def test_with_header_date_column() -> None:
    rows = [["d"], ["2024-01-01"], ["2024-12-31"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "DATE"


def test_with_header_timestamp_column() -> None:
    rows = [["ts"], ["2024-01-01T00:00:00Z"], ["2024-12-31T23:59:59Z"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "TIMESTAMP"


def test_no_header_synthesizes_column_names() -> None:
    rows = [["1", "alice"], ["2", "bob"]]
    schema = autodetect_csv(rows, has_header=False)
    assert [f.name for f in schema] == ["string_field_0", "string_field_1"]
    assert schema[0].type == "INT64"
    assert schema[1].type == "STRING"


def test_empty_cells_dont_constrain_type() -> None:
    rows = [["x"], [""], ["1"], ["", ""], ["2"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "INT64"


def test_mixed_int_and_string_falls_back_to_string() -> None:
    rows = [["x"], ["1"], ["abc"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "STRING"


def test_empty_payload_raises() -> None:
    with pytest.raises(AutodetectError):
        autodetect_csv([], has_header=True)


def test_header_only_no_data_raises() -> None:
    with pytest.raises(AutodetectError):
        autodetect_csv([["a", "b"]], has_header=True)


def test_scientific_notation_float() -> None:
    rows = [["x"], ["1e10"], ["2.5E-3"], ["1.2e+4"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "FLOAT64"


def test_leading_zero_integer_stays_string() -> None:
    rows = [["zip"], ["07030"], ["02110"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "STRING"


def test_timestamp_with_fractional_seconds_and_tz() -> None:
    rows = [["ts"], ["2024-01-01T00:00:00.123Z"], ["2024-12-31T23:59:59+00:00"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "TIMESTAMP"


def test_timestamp_with_trailing_garbage_not_inferred() -> None:
    rows = [["x"], ["2024-01-01T00:00:00garbage"], ["2024-01-02T00:00:00garbage"]]
    schema = autodetect_csv(rows, has_header=True)
    assert schema[0].type == "STRING"
