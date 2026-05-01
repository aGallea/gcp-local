"""Firestore query filter evaluator."""

from typing import Any

from gcp_local.generated.google.firestore.v1 import query_pb2
from gcp_local.services.firestore.errors import InvalidArgument
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.values import DocumentReference, compare, from_proto

_MISSING = object()


def _field(rec: DocumentRecord, path: str) -> Any:
    if path == "__name__":
        return DocumentReference(rec.project, rec.database, rec.path)
    cur: Any = rec.fields
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return _MISSING
        cur = cur[p]
    return cur


def evaluate_filter(filter_proto: query_pb2.StructuredQuery.Filter, rec: DocumentRecord) -> bool:
    which = filter_proto.WhichOneof("filter_type")
    if which == "composite_filter":
        cf = filter_proto.composite_filter
        op = cf.op
        if op == query_pb2.StructuredQuery.CompositeFilter.AND:
            return all(evaluate_filter(f, rec) for f in cf.filters)
        if op == query_pb2.StructuredQuery.CompositeFilter.OR:
            return any(evaluate_filter(f, rec) for f in cf.filters)
        raise InvalidArgument(f"unknown composite op: {op}")
    if which == "field_filter":
        return _eval_field(filter_proto.field_filter, rec)
    if which == "unary_filter":
        return _eval_unary(filter_proto.unary_filter, rec)
    raise InvalidArgument(f"unknown filter type: {which}")


def _eval_field(ff: query_pb2.StructuredQuery.FieldFilter, rec: DocumentRecord) -> bool:
    op = ff.op
    OP = query_pb2.StructuredQuery.FieldFilter.Operator
    lhs = _field(rec, ff.field.field_path)
    rhs = from_proto(ff.value)
    if lhs is _MISSING:
        # Per Firestore: most comparisons against missing fields are false.
        return False
    if op == OP.EQUAL:
        return compare(lhs, rhs) == 0
    if op == OP.NOT_EQUAL:
        return compare(lhs, rhs) != 0
    if op == OP.LESS_THAN:
        return compare(lhs, rhs) < 0
    if op == OP.LESS_THAN_OR_EQUAL:
        return compare(lhs, rhs) <= 0
    if op == OP.GREATER_THAN:
        return compare(lhs, rhs) > 0
    if op == OP.GREATER_THAN_OR_EQUAL:
        return compare(lhs, rhs) >= 0
    if op == OP.ARRAY_CONTAINS:
        return isinstance(lhs, list) and any(compare(x, rhs) == 0 for x in lhs)
    if op == OP.ARRAY_CONTAINS_ANY:
        if not isinstance(lhs, list) or not isinstance(rhs, list):
            return False
        return any(any(compare(x, y) == 0 for x in lhs) for y in rhs)
    if op == OP.IN:
        if not isinstance(rhs, list):
            return False
        return any(compare(lhs, y) == 0 for y in rhs)
    if op == OP.NOT_IN:
        if not isinstance(rhs, list):
            return False
        # NOT_IN excludes null per Firestore docs
        if lhs is None:
            return False
        return not any(compare(lhs, y) == 0 for y in rhs)
    raise InvalidArgument(f"unknown field op: {op}")


def _eval_unary(uf: query_pb2.StructuredQuery.UnaryFilter, rec: DocumentRecord) -> bool:
    OP = query_pb2.StructuredQuery.UnaryFilter.Operator
    val = _field(rec, uf.field.field_path)
    if val is _MISSING:
        # IS_NULL on a missing field is False; IS_NOT_NULL is also False (field absence != null)
        return False
    if uf.op == OP.IS_NAN:
        return isinstance(val, float) and val != val
    if uf.op == OP.IS_NOT_NAN:
        return not (isinstance(val, float) and val != val)
    if uf.op == OP.IS_NULL:
        return val is None
    if uf.op == OP.IS_NOT_NULL:
        return val is not None
    raise InvalidArgument(f"unknown unary op: {uf.op}")
