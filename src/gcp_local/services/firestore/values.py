"""Firestore Value <-> Python codec and type-aware comparator.

Type ordering (per Firestore docs):
  null < bool < number < timestamp < string < bytes < ref < geopoint < array < map

Within-type rules:
- numbers: NaN sorts smallest; int and double compared numerically.
- strings: byte-wise UTF-8.
- bytes: byte-wise.
- arrays: lexicographic.
- maps: by sorted keys, then by value at each key.
- geo points: by latitude, then longitude.
- references: by full path string, byte-wise.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from google.protobuf import timestamp_pb2
from google.type import latlng_pb2

from gcp_local.generated.google.firestore.v1 import document_pb2


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass(frozen=True)
class DocumentReference:
    project: str
    database: str
    path: str

    def to_resource_name(self) -> str:
        return f"projects/{self.project}/databases/{self.database}/documents/{self.path}"

    @classmethod
    def from_resource_name(cls, name: str) -> "DocumentReference":
        # Lazy import to avoid a circular dependency: names imports errors,
        # which doesn't import values, but values importing names would
        # invert that direction unnecessarily.
        from gcp_local.services.firestore.names import parse_document_path

        project, database, path = parse_document_path(name)
        return cls(project, database, path)


_TYPE_ORDER = {
    "null_value": 0,
    "boolean_value": 1,
    "_number": 2,
    "timestamp_value": 3,
    "string_value": 4,
    "bytes_value": 5,
    "reference_value": 6,
    "geo_point_value": 7,
    "array_value": 8,
    "map_value": 9,
}


def _kind(py: object) -> str:
    if py is None:
        return "null_value"
    if isinstance(py, bool):
        return "boolean_value"
    if isinstance(py, (int, float)):
        return "_number"
    if isinstance(py, datetime):
        return "timestamp_value"
    if isinstance(py, str):
        return "string_value"
    if isinstance(py, bytes):
        return "bytes_value"
    if isinstance(py, DocumentReference):
        return "reference_value"
    if isinstance(py, GeoPoint):
        return "geo_point_value"
    if isinstance(py, list):
        return "array_value"
    if isinstance(py, dict):
        return "map_value"
    raise TypeError(f"unsupported value type: {type(py).__name__}")


def to_proto(py: object) -> document_pb2.Value:
    k = _kind(py)
    if k == "null_value":
        return document_pb2.Value(null_value=0)
    if k == "boolean_value":
        return document_pb2.Value(boolean_value=py)
    if k == "_number":
        if isinstance(py, bool):  # bool is a subclass of int — already handled above
            return document_pb2.Value(boolean_value=py)
        if isinstance(py, int):
            return document_pb2.Value(integer_value=py)
        return document_pb2.Value(double_value=py)
    if k == "timestamp_value":
        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(py if py.tzinfo else py.replace(tzinfo=UTC))
        return document_pb2.Value(timestamp_value=ts)
    if k == "string_value":
        return document_pb2.Value(string_value=py)
    if k == "bytes_value":
        return document_pb2.Value(bytes_value=py)
    if k == "reference_value":
        return document_pb2.Value(reference_value=py.to_resource_name())
    if k == "geo_point_value":
        return document_pb2.Value(
            geo_point_value=latlng_pb2.LatLng(latitude=py.lat, longitude=py.lng)
        )
    if k == "array_value":
        return document_pb2.Value(
            array_value=document_pb2.ArrayValue(values=[to_proto(x) for x in py])
        )
    if k == "map_value":
        return document_pb2.Value(
            map_value=document_pb2.MapValue(fields={k2: to_proto(v) for k2, v in py.items()})
        )
    raise AssertionError(f"unhandled kind {k}")


def from_proto(value: document_pb2.Value) -> object:
    which = value.WhichOneof("value_type")
    if which is None or which == "null_value":
        return None
    if which == "boolean_value":
        return value.boolean_value
    if which == "integer_value":
        return int(value.integer_value)
    if which == "double_value":
        return float(value.double_value)
    if which == "timestamp_value":
        return value.timestamp_value.ToDatetime().replace(tzinfo=UTC)
    if which == "string_value":
        return value.string_value
    if which == "bytes_value":
        return bytes(value.bytes_value)
    if which == "reference_value":
        return DocumentReference.from_resource_name(value.reference_value)
    if which == "geo_point_value":
        gp = value.geo_point_value
        return GeoPoint(lat=gp.latitude, lng=gp.longitude)
    if which == "array_value":
        return [from_proto(v) for v in value.array_value.values]
    if which == "map_value":
        return {k: from_proto(v) for k, v in value.map_value.fields.items()}
    raise AssertionError(f"unknown value kind {which}")


def _bucket(py: object) -> int:
    return _TYPE_ORDER[_kind(py)]


def compare(a: object, b: object) -> int:
    """Total order matching Firestore's documented type ordering."""
    ba, bb = _bucket(a), _bucket(b)
    if ba != bb:
        return -1 if ba < bb else 1
    # Same bucket — within-type comparison
    if a is None and b is None:
        return 0
    if isinstance(a, bool):
        return (a > b) - (a < b)
    if isinstance(a, (int, float)):
        a_nan = isinstance(a, float) and math.isnan(a)
        b_nan = isinstance(b, float) and math.isnan(b)
        if a_nan and b_nan:
            return 0
        if a_nan:
            return -1
        if b_nan:
            return 1
        return (float(a) > float(b)) - (float(a) < float(b))
    if isinstance(a, datetime):
        return (a > b) - (a < b)
    if isinstance(a, str):
        ab, bb_ = a.encode("utf-8"), b.encode("utf-8")
        return (ab > bb_) - (ab < bb_)
    if isinstance(a, bytes):
        return (a > b) - (a < b)
    if isinstance(a, DocumentReference):
        ap, bp = a.to_resource_name(), b.to_resource_name()
        return (ap > bp) - (ap < bp)
    if isinstance(a, GeoPoint):
        c = (a.lat > b.lat) - (a.lat < b.lat)
        if c != 0:
            return c
        return (a.lng > b.lng) - (a.lng < b.lng)
    if isinstance(a, list):
        for x, y in zip(a, b, strict=False):
            c = compare(x, y)
            if c != 0:
                return c
        return (len(a) > len(b)) - (len(a) < len(b))
    if isinstance(a, dict):
        a_keys = sorted(a.keys())
        b_keys = sorted(b.keys())
        for ak, bk in zip(a_keys, b_keys, strict=False):
            c = (ak > bk) - (ak < bk)
            if c != 0:
                return c
            c = compare(a[ak], b[bk])
            if c != 0:
                return c
        return (len(a_keys) > len(b_keys)) - (len(a_keys) < len(b_keys))
    raise TypeError(f"unsupported comparison: {type(a).__name__}")
