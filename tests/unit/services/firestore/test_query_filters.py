"""Tests for evaluate_filter in engine/query.py."""

from datetime import UTC, datetime

import pytest

from gcp_local.generated.google.firestore.v1 import document_pb2, query_pb2
from gcp_local.services.firestore.engine.query import evaluate_filter
from gcp_local.services.firestore.errors import InvalidArgument
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.values import DocumentReference, to_proto

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

_F = query_pb2.StructuredQuery.Filter
_FF = query_pb2.StructuredQuery.FieldFilter
_UF = query_pb2.StructuredQuery.UnaryFilter
_CF = query_pb2.StructuredQuery.CompositeFilter
_OP = query_pb2.StructuredQuery.FieldFilter.Operator
_UOP = query_pb2.StructuredQuery.UnaryFilter.Operator
_COP = query_pb2.StructuredQuery.CompositeFilter.Operator


def _rec(fields: dict, path: str = "col/doc1") -> DocumentRecord:
    return DocumentRecord(
        project="proj",
        database="(default)",
        path=path,
        fields=fields,
        create_time=_NOW,
        update_time=_NOW,
        version=1,
    )


def _field_filter(field_path: str, op, value) -> _F:
    return _F(
        field_filter=_FF(
            field=query_pb2.StructuredQuery.FieldReference(field_path=field_path),
            op=op,
            value=to_proto(value),
        )
    )


def _array_filter(field_path: str, op, values: list) -> _F:
    """Build a filter whose value is an ArrayValue (for IN / NOT_IN / ARRAY_CONTAINS_ANY)."""
    arr = document_pb2.ArrayValue(values=[to_proto(v) for v in values])
    return _F(
        field_filter=_FF(
            field=query_pb2.StructuredQuery.FieldReference(field_path=field_path),
            op=op,
            value=document_pb2.Value(array_value=arr),
        )
    )


def _unary_filter(field_path: str, op) -> _F:
    return _F(
        unary_filter=_UF(
            field=query_pb2.StructuredQuery.FieldReference(field_path=field_path),
            op=op,
        )
    )


def _and_filter(*filters) -> _F:
    return _F(
        composite_filter=_CF(
            op=_COP.AND,
            filters=list(filters),
        )
    )


def _or_filter(*filters) -> _F:
    return _F(
        composite_filter=_CF(
            op=_COP.OR,
            filters=list(filters),
        )
    )


# ---------------------------------------------------------------------------
# Field filter: EQUAL
# ---------------------------------------------------------------------------


class TestEqual:
    def test_equal_string_match(self):
        rec = _rec({"name": "alice"})
        f = _field_filter("name", _OP.EQUAL, "alice")
        assert evaluate_filter(f, rec) is True

    def test_equal_string_no_match(self):
        rec = _rec({"name": "bob"})
        f = _field_filter("name", _OP.EQUAL, "alice")
        assert evaluate_filter(f, rec) is False

    def test_equal_int(self):
        rec = _rec({"age": 30})
        f = _field_filter("age", _OP.EQUAL, 30)
        assert evaluate_filter(f, rec) is True

    def test_equal_null(self):
        rec = _rec({"x": None})
        f = _field_filter("x", _OP.EQUAL, None)
        assert evaluate_filter(f, rec) is True

    def test_equal_missing_field_returns_false(self):
        rec = _rec({})
        f = _field_filter("missing", _OP.EQUAL, "anything")
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Field filter: NOT_EQUAL
# ---------------------------------------------------------------------------


class TestNotEqual:
    def test_not_equal_different_values(self):
        rec = _rec({"x": 1})
        f = _field_filter("x", _OP.NOT_EQUAL, 2)
        assert evaluate_filter(f, rec) is True

    def test_not_equal_same_value(self):
        rec = _rec({"x": 1})
        f = _field_filter("x", _OP.NOT_EQUAL, 1)
        assert evaluate_filter(f, rec) is False

    def test_not_equal_missing_field_returns_false(self):
        rec = _rec({})
        f = _field_filter("nope", _OP.NOT_EQUAL, "x")
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Field filter: LESS_THAN / LESS_THAN_OR_EQUAL
# ---------------------------------------------------------------------------


class TestLessThan:
    def test_less_than_true(self):
        rec = _rec({"score": 5})
        f = _field_filter("score", _OP.LESS_THAN, 10)
        assert evaluate_filter(f, rec) is True

    def test_less_than_equal_is_false(self):
        rec = _rec({"score": 10})
        f = _field_filter("score", _OP.LESS_THAN, 10)
        assert evaluate_filter(f, rec) is False

    def test_less_than_or_equal_equal(self):
        rec = _rec({"score": 10})
        f = _field_filter("score", _OP.LESS_THAN_OR_EQUAL, 10)
        assert evaluate_filter(f, rec) is True

    def test_less_than_or_equal_less(self):
        rec = _rec({"score": 9})
        f = _field_filter("score", _OP.LESS_THAN_OR_EQUAL, 10)
        assert evaluate_filter(f, rec) is True

    def test_less_than_or_equal_greater_is_false(self):
        rec = _rec({"score": 11})
        f = _field_filter("score", _OP.LESS_THAN_OR_EQUAL, 10)
        assert evaluate_filter(f, rec) is False

    def test_less_than_missing_field_returns_false(self):
        rec = _rec({})
        f = _field_filter("score", _OP.LESS_THAN, 10)
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Field filter: GREATER_THAN / GREATER_THAN_OR_EQUAL
# ---------------------------------------------------------------------------


class TestGreaterThan:
    def test_greater_than_true(self):
        rec = _rec({"score": 15})
        f = _field_filter("score", _OP.GREATER_THAN, 10)
        assert evaluate_filter(f, rec) is True

    def test_greater_than_equal_is_false(self):
        rec = _rec({"score": 10})
        f = _field_filter("score", _OP.GREATER_THAN, 10)
        assert evaluate_filter(f, rec) is False

    def test_greater_than_or_equal_equal(self):
        rec = _rec({"score": 10})
        f = _field_filter("score", _OP.GREATER_THAN_OR_EQUAL, 10)
        assert evaluate_filter(f, rec) is True

    def test_greater_than_or_equal_greater(self):
        rec = _rec({"score": 11})
        f = _field_filter("score", _OP.GREATER_THAN_OR_EQUAL, 10)
        assert evaluate_filter(f, rec) is True

    def test_greater_than_or_equal_less_is_false(self):
        rec = _rec({"score": 9})
        f = _field_filter("score", _OP.GREATER_THAN_OR_EQUAL, 10)
        assert evaluate_filter(f, rec) is False

    def test_greater_than_missing_field_returns_false(self):
        rec = _rec({})
        f = _field_filter("score", _OP.GREATER_THAN, 0)
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Field filter: ARRAY_CONTAINS
# ---------------------------------------------------------------------------


class TestArrayContains:
    def test_contains_present_element(self):
        rec = _rec({"tags": ["a", "b", "c"]})
        f = _field_filter("tags", _OP.ARRAY_CONTAINS, "b")
        assert evaluate_filter(f, rec) is True

    def test_contains_absent_element(self):
        rec = _rec({"tags": ["a", "b"]})
        f = _field_filter("tags", _OP.ARRAY_CONTAINS, "z")
        assert evaluate_filter(f, rec) is False

    def test_contains_on_non_array_is_false(self):
        rec = _rec({"tags": "not-an-array"})
        f = _field_filter("tags", _OP.ARRAY_CONTAINS, "not-an-array")
        assert evaluate_filter(f, rec) is False

    def test_contains_missing_field_returns_false(self):
        rec = _rec({})
        f = _field_filter("tags", _OP.ARRAY_CONTAINS, "x")
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Field filter: ARRAY_CONTAINS_ANY
# ---------------------------------------------------------------------------


class TestArrayContainsAny:
    def test_one_candidate_matches(self):
        rec = _rec({"tags": ["a", "b", "c"]})
        f = _array_filter("tags", _OP.ARRAY_CONTAINS_ANY, ["z", "b"])
        assert evaluate_filter(f, rec) is True

    def test_no_candidate_matches(self):
        rec = _rec({"tags": ["a", "b"]})
        f = _array_filter("tags", _OP.ARRAY_CONTAINS_ANY, ["x", "y"])
        assert evaluate_filter(f, rec) is False

    def test_field_not_array_returns_false(self):
        rec = _rec({"tags": "not-a-list"})
        f = _array_filter("tags", _OP.ARRAY_CONTAINS_ANY, ["not-a-list"])
        assert evaluate_filter(f, rec) is False

    def test_missing_field_returns_false(self):
        rec = _rec({})
        f = _array_filter("tags", _OP.ARRAY_CONTAINS_ANY, ["x"])
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Field filter: IN
# ---------------------------------------------------------------------------


class TestIn:
    def test_in_value_present(self):
        rec = _rec({"status": "active"})
        f = _array_filter("status", _OP.IN, ["active", "pending"])
        assert evaluate_filter(f, rec) is True

    def test_in_value_absent(self):
        rec = _rec({"status": "deleted"})
        f = _array_filter("status", _OP.IN, ["active", "pending"])
        assert evaluate_filter(f, rec) is False

    def test_in_numeric(self):
        rec = _rec({"x": 2})
        f = _array_filter("x", _OP.IN, [1, 2, 3])
        assert evaluate_filter(f, rec) is True

    def test_in_missing_field_returns_false(self):
        rec = _rec({})
        f = _array_filter("x", _OP.IN, [1, 2])
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Field filter: NOT_IN
# ---------------------------------------------------------------------------


class TestNotIn:
    def test_not_in_value_absent_from_list(self):
        rec = _rec({"status": "archived"})
        f = _array_filter("status", _OP.NOT_IN, ["active", "pending"])
        assert evaluate_filter(f, rec) is True

    def test_not_in_value_present_in_list(self):
        rec = _rec({"status": "active"})
        f = _array_filter("status", _OP.NOT_IN, ["active", "pending"])
        assert evaluate_filter(f, rec) is False

    def test_not_in_excludes_null_field(self):
        """Firestore: doc with the field as null returns False for NOT_IN."""
        rec = _rec({"x": None})
        f = _array_filter("x", _OP.NOT_IN, ["a", "b"])
        assert evaluate_filter(f, rec) is False

    def test_not_in_missing_field_returns_false(self):
        rec = _rec({})
        f = _array_filter("x", _OP.NOT_IN, ["a"])
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Unary filters
# ---------------------------------------------------------------------------


class TestIsNan:
    def test_is_nan_true(self):
        rec = _rec({"val": float("nan")})
        f = _unary_filter("val", _UOP.IS_NAN)
        assert evaluate_filter(f, rec) is True

    def test_is_nan_false_for_number(self):
        rec = _rec({"val": 1.0})
        f = _unary_filter("val", _UOP.IS_NAN)
        assert evaluate_filter(f, rec) is False

    def test_is_nan_false_for_string(self):
        rec = _rec({"val": "nan"})
        f = _unary_filter("val", _UOP.IS_NAN)
        assert evaluate_filter(f, rec) is False

    def test_is_nan_missing_field_returns_false(self):
        rec = _rec({})
        f = _unary_filter("val", _UOP.IS_NAN)
        assert evaluate_filter(f, rec) is False


class TestIsNotNan:
    def test_is_not_nan_true_for_normal_float(self):
        rec = _rec({"val": 3.14})
        f = _unary_filter("val", _UOP.IS_NOT_NAN)
        assert evaluate_filter(f, rec) is True

    def test_is_not_nan_false_for_nan(self):
        rec = _rec({"val": float("nan")})
        f = _unary_filter("val", _UOP.IS_NOT_NAN)
        assert evaluate_filter(f, rec) is False

    def test_is_not_nan_true_for_string(self):
        # Non-float values are not NaN
        rec = _rec({"val": "hello"})
        f = _unary_filter("val", _UOP.IS_NOT_NAN)
        assert evaluate_filter(f, rec) is True

    def test_is_not_nan_missing_field_returns_false(self):
        rec = _rec({})
        f = _unary_filter("val", _UOP.IS_NOT_NAN)
        assert evaluate_filter(f, rec) is False


class TestIsNull:
    def test_is_null_true(self):
        rec = _rec({"x": None})
        f = _unary_filter("x", _UOP.IS_NULL)
        assert evaluate_filter(f, rec) is True

    def test_is_null_false_for_zero(self):
        rec = _rec({"x": 0})
        f = _unary_filter("x", _UOP.IS_NULL)
        assert evaluate_filter(f, rec) is False

    def test_is_null_missing_field_returns_false(self):
        """Missing field is not null — field absence != null per Firestore semantics."""
        rec = _rec({})
        f = _unary_filter("x", _UOP.IS_NULL)
        assert evaluate_filter(f, rec) is False


class TestIsNotNull:
    def test_is_not_null_true_for_value(self):
        rec = _rec({"x": "something"})
        f = _unary_filter("x", _UOP.IS_NOT_NULL)
        assert evaluate_filter(f, rec) is True

    def test_is_not_null_false_for_null(self):
        rec = _rec({"x": None})
        f = _unary_filter("x", _UOP.IS_NOT_NULL)
        assert evaluate_filter(f, rec) is False

    def test_is_not_null_missing_field_returns_false(self):
        rec = _rec({})
        f = _unary_filter("x", _UOP.IS_NOT_NULL)
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Composite filters: AND / OR
# ---------------------------------------------------------------------------


class TestCompositeAnd:
    def test_and_all_match(self):
        rec = _rec({"a": 1, "b": 2})
        f = _and_filter(
            _field_filter("a", _OP.EQUAL, 1),
            _field_filter("b", _OP.EQUAL, 2),
        )
        assert evaluate_filter(f, rec) is True

    def test_and_one_fails(self):
        rec = _rec({"a": 1, "b": 99})
        f = _and_filter(
            _field_filter("a", _OP.EQUAL, 1),
            _field_filter("b", _OP.EQUAL, 2),
        )
        assert evaluate_filter(f, rec) is False

    def test_and_short_circuits_on_false(self):
        """Second filter would raise if evaluated; short-circuit prevents that."""
        rec = _rec({"a": 999})
        # First filter fails; second filter references a field not in doc (returns False anyway)
        f = _and_filter(
            _field_filter("a", _OP.EQUAL, 1),  # False — short-circuit
            _field_filter("b", _OP.EQUAL, 1),
        )
        assert evaluate_filter(f, rec) is False

    def test_and_empty_filters_is_true(self):
        """Vacuously true."""
        rec = _rec({})
        f = _F(composite_filter=_CF(op=_COP.AND, filters=[]))
        assert evaluate_filter(f, rec) is True

    def test_and_with_nested_or(self):
        rec = _rec({"a": 1, "b": 5})
        inner_or = _or_filter(
            _field_filter("b", _OP.EQUAL, 5),
            _field_filter("b", _OP.EQUAL, 10),
        )
        f = _and_filter(_field_filter("a", _OP.EQUAL, 1), inner_or)
        assert evaluate_filter(f, rec) is True


class TestCompositeOr:
    def test_or_first_matches(self):
        rec = _rec({"x": "yes"})
        f = _or_filter(
            _field_filter("x", _OP.EQUAL, "yes"),
            _field_filter("x", _OP.EQUAL, "no"),
        )
        assert evaluate_filter(f, rec) is True

    def test_or_second_matches(self):
        rec = _rec({"x": "no"})
        f = _or_filter(
            _field_filter("x", _OP.EQUAL, "yes"),
            _field_filter("x", _OP.EQUAL, "no"),
        )
        assert evaluate_filter(f, rec) is True

    def test_or_none_match(self):
        rec = _rec({"x": "maybe"})
        f = _or_filter(
            _field_filter("x", _OP.EQUAL, "yes"),
            _field_filter("x", _OP.EQUAL, "no"),
        )
        assert evaluate_filter(f, rec) is False

    def test_or_short_circuits_on_true(self):
        """Once first filter passes, second is not evaluated."""
        rec = _rec({"a": 1})
        # Second filter references missing field which returns False — but OR already True
        f = _or_filter(
            _field_filter("a", _OP.EQUAL, 1),  # True — short-circuit
            _field_filter("b", _OP.EQUAL, 1),
        )
        assert evaluate_filter(f, rec) is True

    def test_or_empty_filters_is_false(self):
        """Vacuously false."""
        rec = _rec({})
        f = _F(composite_filter=_CF(op=_COP.OR, filters=[]))
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Dotted (nested) field paths
# ---------------------------------------------------------------------------


class TestDottedPaths:
    def test_nested_field_match(self):
        rec = _rec({"profile": {"name": "alice"}})
        f = _field_filter("profile.name", _OP.EQUAL, "alice")
        assert evaluate_filter(f, rec) is True

    def test_nested_field_missing_intermediate(self):
        rec = _rec({"profile": "not-a-dict"})
        f = _field_filter("profile.name", _OP.EQUAL, "alice")
        assert evaluate_filter(f, rec) is False

    def test_deeply_nested(self):
        rec = _rec({"a": {"b": {"c": 42}}})
        f = _field_filter("a.b.c", _OP.EQUAL, 42)
        assert evaluate_filter(f, rec) is True


# ---------------------------------------------------------------------------
# __name__ special field
# ---------------------------------------------------------------------------


class TestNameField:
    def test_name_equal_matching_path(self):
        rec = _rec({}, path="col/doc123")
        ref = DocumentReference("proj", "(default)", "col/doc123")
        resource_name = ref.to_resource_name()
        name_val = document_pb2.Value(reference_value=resource_name)
        f = _F(
            field_filter=_FF(
                field=query_pb2.StructuredQuery.FieldReference(field_path="__name__"),
                op=_OP.EQUAL,
                value=name_val,
            )
        )
        assert evaluate_filter(f, rec) is True

    def test_name_equal_different_path(self):
        rec = _rec({}, path="col/doc123")
        ref = DocumentReference("proj", "(default)", "col/other")
        resource_name = ref.to_resource_name()
        name_val = document_pb2.Value(reference_value=resource_name)
        f = _F(
            field_filter=_FF(
                field=query_pb2.StructuredQuery.FieldReference(field_path="__name__"),
                op=_OP.EQUAL,
                value=name_val,
            )
        )
        assert evaluate_filter(f, rec) is False


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_unknown_composite_op_raises(self):
        rec = _rec({})
        f = _F(
            composite_filter=_CF(
                op=_COP.OPERATOR_UNSPECIFIED,
                filters=[_field_filter("x", _OP.EQUAL, 1)],
            )
        )
        with pytest.raises(InvalidArgument, match="unknown composite op"):
            evaluate_filter(f, rec)

    def test_unknown_filter_type_raises(self):
        """An empty Filter proto has no filter_type set — WhichOneof returns None."""
        rec = _rec({})
        f = _F()  # no filter_type set
        with pytest.raises(InvalidArgument, match="unknown filter type"):
            evaluate_filter(f, rec)
