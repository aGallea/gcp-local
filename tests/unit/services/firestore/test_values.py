import math

import pytest

from gcp_local.generated.google.firestore.v1 import document_pb2
from gcp_local.services.firestore.values import (
    DocumentReference,
    GeoPoint,
    compare,
    from_proto,
    to_proto,
)


def _v(**kwargs) -> document_pb2.Value:
    return document_pb2.Value(**kwargs)


class TestRoundTrip:
    @pytest.mark.parametrize(
        "py_val, kind",
        [
            (None, "null_value"),
            (True, "boolean_value"),
            (False, "boolean_value"),
            (42, "integer_value"),
            (3.14, "double_value"),
            (float("nan"), "double_value"),
            ("hello", "string_value"),
            (b"\x00\x01", "bytes_value"),
            ([1, "two", None], "array_value"),
            ({"a": 1, "b": "two"}, "map_value"),
        ],
    )
    def test_round_trip(self, py_val, kind):
        proto = to_proto(py_val)
        assert proto.WhichOneof("value_type") == kind
        if isinstance(py_val, float) and math.isnan(py_val):
            assert math.isnan(from_proto(proto))
        else:
            assert from_proto(proto) == py_val

    def test_geo_point_round_trip(self):
        gp = GeoPoint(lat=37.4, lng=-122.1)
        proto = to_proto(gp)
        assert proto.WhichOneof("value_type") == "geo_point_value"
        assert from_proto(proto) == gp

    def test_reference_round_trip(self):
        ref = DocumentReference(project="p", database="(default)", path="users/a")
        proto = to_proto(ref)
        assert proto.WhichOneof("value_type") == "reference_value"
        assert proto.reference_value == "projects/p/databases/(default)/documents/users/a"
        assert from_proto(proto) == ref


class TestCompareTypeOrdering:
    @pytest.mark.parametrize(
        "a, b",
        [
            (None, False),
            (False, 0),
            (0, "x"),
            ("x", b"x"),
            (b"x", DocumentReference("p", "(default)", "x/y")),
            (DocumentReference("p", "(default)", "x/y"), GeoPoint(0, 0)),
            (GeoPoint(0, 0), [0]),
            ([0], {"a": 0}),
        ],
    )
    def test_type_order(self, a, b):
        # All across-type comparisons: a < b
        assert compare(a, b) < 0
        assert compare(b, a) > 0


class TestCompareWithinType:
    def test_nan_sorts_smallest_among_numbers(self):
        assert compare(float("nan"), 0) < 0
        assert compare(float("nan"), float("-inf")) < 0
        assert compare(float("nan"), float("nan")) == 0

    def test_int_double_mix(self):
        assert compare(1, 1.5) < 0
        assert compare(2, 1.5) > 0
        assert compare(1, 1.0) == 0

    def test_strings_byte_wise(self):
        assert compare("a", "b") < 0
        assert compare("z", "aa") > 0  # byte-wise, "z" (0x7A) > "a" (0x61)

    def test_arrays_lexicographic(self):
        assert compare([1, 2], [1, 3]) < 0
        assert compare([1], [1, 0]) < 0  # shorter prefix sorts first
        assert compare([1, 2], [1, 2]) == 0

    def test_maps_key_then_value(self):
        # Firestore maps compare by sorted keys, then by value at each key
        assert compare({"a": 1}, {"a": 2}) < 0
        assert compare({"a": 1}, {"b": 1}) < 0  # key "a" < "b"

    def test_geo_point_compare_lat_then_lng(self):
        assert compare(GeoPoint(1.0, 0.0), GeoPoint(2.0, 0.0)) < 0
        assert compare(GeoPoint(1.0, 0.0), GeoPoint(1.0, 1.0)) < 0
