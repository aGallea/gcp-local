"""Unit tests for the Firestore aggregation engine (Task 11)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from google.protobuf.wrappers_pb2 import Int64Value

from gcp_local.generated.google.firestore.v1 import query_pb2
from gcp_local.services.firestore.engine.aggregations import aggregate
from gcp_local.services.firestore.models import DocumentRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _rec(path: str, fields: dict) -> DocumentRecord:
    return DocumentRecord(
        project="p",
        database="d",
        path=path,
        fields=fields,
        create_time=_NOW,
        update_time=_NOW,
        version=1,
    )


def _count_agg(
    alias: str = "", up_to: int | None = None
) -> query_pb2.StructuredAggregationQuery.Aggregation:
    cnt = query_pb2.StructuredAggregationQuery.Aggregation.Count()
    if up_to is not None:
        cnt.up_to.CopyFrom(Int64Value(value=up_to))
    return query_pb2.StructuredAggregationQuery.Aggregation(count=cnt, alias=alias)


def _sum_agg(field_path: str, alias: str = "") -> query_pb2.StructuredAggregationQuery.Aggregation:
    f = query_pb2.StructuredQuery.FieldReference(field_path=field_path)
    s = query_pb2.StructuredAggregationQuery.Aggregation.Sum(field=f)
    return query_pb2.StructuredAggregationQuery.Aggregation(sum=s, alias=alias)


def _avg_agg(field_path: str, alias: str = "") -> query_pb2.StructuredAggregationQuery.Aggregation:
    f = query_pb2.StructuredQuery.FieldReference(field_path=field_path)
    a = query_pb2.StructuredAggregationQuery.Aggregation.Avg(field=f)
    return query_pb2.StructuredAggregationQuery.Aggregation(avg=a, alias=alias)


# ---------------------------------------------------------------------------
# COUNT tests
# ---------------------------------------------------------------------------


def test_count_empty_records_returns_zero() -> None:
    result = aggregate([], [_count_agg(alias="n")])
    assert result == {"n": 0}


def test_count_non_empty_records() -> None:
    records = [_rec(f"col/doc{i}", {}) for i in range(5)]
    result = aggregate(records, [_count_agg(alias="total")])
    assert result == {"total": 5}


def test_count_with_up_to_clamps_result() -> None:
    records = [_rec(f"col/doc{i}", {}) for i in range(10)]
    result = aggregate(records, [_count_agg(alias="n", up_to=3)])
    assert result == {"n": 3}


def test_count_up_to_greater_than_count_no_clamp() -> None:
    records = [_rec(f"col/doc{i}", {}) for i in range(4)]
    result = aggregate(records, [_count_agg(alias="n", up_to=100)])
    assert result == {"n": 4}


def test_count_alias_defaults_to_operator_name() -> None:
    """When alias is empty the key should be 'count'."""
    records = [_rec("col/doc1", {})]
    result = aggregate(records, [_count_agg(alias="")])
    assert "count" in result
    assert result["count"] == 1


# ---------------------------------------------------------------------------
# SUM tests
# ---------------------------------------------------------------------------


def test_sum_int_plus_int_returns_int() -> None:
    records = [
        _rec("col/a", {"score": 3}),
        _rec("col/b", {"score": 7}),
    ]
    result = aggregate(records, [_sum_agg("score", alias="total")])
    assert result["total"] == 10
    assert isinstance(result["total"], int)


def test_sum_mixed_int_and_float_returns_float() -> None:
    records = [
        _rec("col/a", {"x": 1}),
        _rec("col/b", {"x": 2.5}),
    ]
    result = aggregate(records, [_sum_agg("x", alias="s")])
    assert result["s"] == pytest.approx(3.5)
    assert isinstance(result["s"], float)


def test_sum_ignores_non_numeric_fields() -> None:
    records = [
        _rec("col/a", {"v": "hello"}),
        _rec("col/b", {"v": 5}),
        _rec("col/c", {"v": None}),
    ]
    result = aggregate(records, [_sum_agg("v", alias="s")])
    assert result["s"] == 5
    assert isinstance(result["s"], int)


def test_sum_ignores_bool_fields() -> None:
    """Booleans must not be treated as numeric even though bool is a subclass of int."""
    records = [
        _rec("col/a", {"v": True}),
        _rec("col/b", {"v": False}),
        _rec("col/c", {"v": 10}),
    ]
    result = aggregate(records, [_sum_agg("v", alias="s")])
    assert result["s"] == 10
    assert isinstance(result["s"], int)


def test_sum_missing_field_skipped() -> None:
    records = [
        _rec("col/a", {"score": 5}),
        _rec("col/b", {}),  # missing field → skip
    ]
    result = aggregate(records, [_sum_agg("score", alias="s")])
    assert result["s"] == 5


# ---------------------------------------------------------------------------
# AVG tests
# ---------------------------------------------------------------------------


def test_avg_returns_float() -> None:
    records = [
        _rec("col/a", {"v": 10}),
        _rec("col/b", {"v": 20}),
    ]
    result = aggregate(records, [_avg_agg("v", alias="a")])
    assert result["a"] == pytest.approx(15.0)
    assert isinstance(result["a"], float)


def test_avg_returns_none_on_empty_match() -> None:
    records = [_rec("col/a", {"other": 5})]
    result = aggregate(records, [_avg_agg("v", alias="a")])
    assert result["a"] is None


def test_avg_with_mixed_types() -> None:
    records = [
        _rec("col/a", {"v": 3}),
        _rec("col/b", {"v": 7.0}),
        _rec("col/c", {"v": "skip"}),
    ]
    result = aggregate(records, [_avg_agg("v", alias="a")])
    assert result["a"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Multiple aggregations in one call
# ---------------------------------------------------------------------------


def test_multiple_aggregations_keyed_by_alias() -> None:
    records = [
        _rec("col/a", {"score": 10}),
        _rec("col/b", {"score": 20}),
        _rec("col/c", {"score": 30}),
    ]
    aggs = [
        _count_agg(alias="n"),
        _sum_agg("score", alias="total"),
        _avg_agg("score", alias="mean"),
    ]
    result = aggregate(records, aggs)
    assert result["n"] == 3
    assert result["total"] == 60
    assert isinstance(result["total"], int)
    assert result["mean"] == pytest.approx(20.0)
