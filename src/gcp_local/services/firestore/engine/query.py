"""Firestore query filter evaluator and full query pipeline."""

import functools
from typing import Any

from gcp_local.generated.google.firestore.v1 import query_pb2
from gcp_local.services.firestore.errors import InvalidArgument
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.storage import FirestoreStorage
from gcp_local.services.firestore.values import DocumentReference, compare, from_proto

_MISSING = object()


def _from_selectors(
    structured_query: query_pb2.StructuredQuery,
) -> list[query_pb2.StructuredQuery.CollectionSelector]:
    """Return the StructuredQuery.from list, robust to attribute-naming
    differences between protobuf versions and proto-plus contamination.

    Some protobuf runtimes expose the (reserved-word) ``from`` field as
    ``from``; others rename it to ``from_``.  Either form may raise
    ``AttributeError`` or ``ValueError`` on the wrong runtime, so we try
    both inside a guard.
    """
    for name in ("from_", "from"):
        try:
            value = getattr(structured_query, name)
        except (AttributeError, ValueError):
            continue
        return list(value)
    return []


# ---------------------------------------------------------------------------
# Inequality operators — used to detect implicit orderBy fields
# ---------------------------------------------------------------------------

_INEQUALITY_OPS = frozenset(
    [
        query_pb2.StructuredQuery.FieldFilter.Operator.LESS_THAN,
        query_pb2.StructuredQuery.FieldFilter.Operator.LESS_THAN_OR_EQUAL,
        query_pb2.StructuredQuery.FieldFilter.Operator.GREATER_THAN,
        query_pb2.StructuredQuery.FieldFilter.Operator.GREATER_THAN_OR_EQUAL,
        query_pb2.StructuredQuery.FieldFilter.Operator.NOT_EQUAL,
        query_pb2.StructuredQuery.FieldFilter.Operator.NOT_IN,
    ]
)


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


# ---------------------------------------------------------------------------
# orderBy / cursor helpers
# ---------------------------------------------------------------------------


def _inequality_fields(filter_proto: query_pb2.StructuredQuery.Filter) -> list[str]:
    """Recursively collect field paths that use an inequality operator."""
    which = filter_proto.WhichOneof("filter_type")
    if which == "composite_filter":
        seen: list[str] = []
        for f in filter_proto.composite_filter.filters:
            for fp in _inequality_fields(f):
                if fp not in seen:
                    seen.append(fp)
        return seen
    if which == "field_filter":
        ff = filter_proto.field_filter
        if ff.op in _INEQUALITY_OPS:
            return [ff.field.field_path]
        return []
    return []


def _effective_order_by(
    query: query_pb2.StructuredQuery,
) -> list[query_pb2.StructuredQuery.Order]:
    """
    Return the effective orderBy list:
    1. Implicit orderBy for inequality filter fields (prepended, if not already present).
    2. Explicit orderBy from the query.
    3. Implicit __name__ tiebreak (direction = last explicit field's direction, or ASC).
    """
    _DIR = query_pb2.StructuredQuery.Direction
    _Order = query_pb2.StructuredQuery.Order
    _FieldRef = query_pb2.StructuredQuery.FieldReference

    explicit = list(query.order_by)
    explicit_paths = {o.field.field_path for o in explicit}

    # 1. Implicit orderBy for inequality fields (prepend only if absent)
    ineq_fields: list[str] = []
    if query.HasField("where"):
        ineq_fields = _inequality_fields(query.where)

    orders: list[query_pb2.StructuredQuery.Order] = []
    for fp in ineq_fields:
        if fp not in explicit_paths and fp != "__name__":
            orders.append(
                _Order(
                    field=_FieldRef(field_path=fp),
                    direction=_DIR.ASCENDING,
                )
            )

    orders.extend(explicit)

    # 2. Implicit __name__ tiebreak if not already present
    if "__name__" not in {o.field.field_path for o in orders}:
        last_dir = orders[-1].direction if orders else _DIR.ASCENDING
        tiebreak_dir = last_dir if last_dir != _DIR.DIRECTION_UNSPECIFIED else _DIR.ASCENDING
        orders.append(
            _Order(
                field=_FieldRef(field_path="__name__"),
                direction=tiebreak_dir,
            )
        )

    return orders


def _doc_orderby_key(
    rec: DocumentRecord,
    orders: list[query_pb2.StructuredQuery.Order],
) -> list[Any]:
    """Extract an ordered list of field values for sorting."""
    return [_field(rec, o.field.field_path) for o in orders]


def _compare_keys(
    key_a: list[Any],
    key_b: list[Any],
    orders: list[query_pb2.StructuredQuery.Order],
) -> int:
    """
    Compare two key tuples honoring per-field direction.
    _MISSING values sort smaller than any real value.
    Comparison length is min(len(key_a), len(key_b), len(orders)).
    """
    _DIR = query_pb2.StructuredQuery.Direction
    n = min(len(key_a), len(key_b), len(orders))
    for i in range(n):
        a, b = key_a[i], key_b[i]
        direction = orders[i].direction
        if a is _MISSING and b is _MISSING:
            c = 0
        elif a is _MISSING:
            c = -1
        elif b is _MISSING:
            c = 1
        else:
            c = compare(a, b)
        if c == 0:
            continue
        if direction == _DIR.DESCENDING:
            c = -c
        return c
    return 0


def _cursor_cmp(
    cursor: query_pb2.Cursor,
    key: list[Any],
    orders: list[query_pb2.StructuredQuery.Order],
) -> int:
    """
    Return compare(cursor_key, doc_key) for the first len(cursor.values) fields.
    Only compares up to len(cursor.values), ignoring extra orderBy fields.
    """
    cursor_key = [from_proto(v) for v in cursor.values]
    n = len(cursor_key)
    # Trim orders and doc key to cursor length for partial cursor semantics
    return _compare_keys(cursor_key, key[:n], orders[:n])


def _passes_start_cursor(
    cursor: query_pb2.Cursor,
    key: list[Any],
    orders: list[query_pb2.StructuredQuery.Order],
) -> bool:
    """
    Proto semantics for start cursor:
      before=True  → start_at (inclusive): include doc if cursor <= doc
      before=False → start_after (exclusive): include doc if cursor < doc
    """
    cmp = _cursor_cmp(cursor, key, orders)
    if cursor.before:
        # start_at: include when cursor key <= doc key
        return cmp <= 0
    else:
        # start_after: include when cursor key < doc key
        return cmp < 0


def _passes_end_cursor(
    cursor: query_pb2.Cursor,
    key: list[Any],
    orders: list[query_pb2.StructuredQuery.Order],
) -> bool:
    """
    Proto semantics for end cursor:
      before=True  → end_before (exclusive): include doc if doc < cursor
      before=False → end_at (inclusive): include doc if doc <= cursor
    """
    cmp = _cursor_cmp(cursor, key, orders)
    if cursor.before:
        # end_before: include when doc key < cursor key (i.e. cursor > doc → cmp > 0)
        return cmp > 0
    else:
        # end_at: include when doc key <= cursor key (i.e. cursor >= doc → cmp >= 0)
        return cmp >= 0


# ---------------------------------------------------------------------------
# Full query pipeline
# ---------------------------------------------------------------------------


async def run_query(
    storage: FirestoreStorage,
    project: str,
    database: str,
    structured_query: query_pb2.StructuredQuery,
    parent_path: str = "",
) -> list[DocumentRecord]:
    """
    Execute a StructuredQuery against storage and return matching DocumentRecords.

    Pipeline:
      candidates → filter → orderBy → cursors → offset → limit → return
    """
    from_selectors = _from_selectors(structured_query)
    if not from_selectors:
        return []

    selector = from_selectors[0]
    collection_id = selector.collection_id
    all_descendants = selector.all_descendants

    # 1. Candidate documents
    candidates: list[DocumentRecord] = []
    async for rec in storage.iter_collection(
        project,
        database,
        collection_id,
        all_descendants=all_descendants,
        parent_path=parent_path,
    ):
        candidates.append(rec)

    # 2. Apply where filter
    if structured_query.HasField("where"):
        candidates = [r for r in candidates if evaluate_filter(structured_query.where, r)]

    # 3. Compute effective orderBy (with implicit prepends and __name__ tiebreak)
    orders = _effective_order_by(structured_query)

    # 4. Stable sort
    def _cmp(a: DocumentRecord, b: DocumentRecord) -> int:
        ka = _doc_orderby_key(a, orders)
        kb = _doc_orderby_key(b, orders)
        return _compare_keys(ka, kb, orders)

    candidates = sorted(candidates, key=functools.cmp_to_key(_cmp))

    # 5. Apply cursors
    if structured_query.HasField("start_at"):
        cursor = structured_query.start_at
        candidates = [
            r
            for r in candidates
            if _passes_start_cursor(cursor, _doc_orderby_key(r, orders), orders)
        ]

    if structured_query.HasField("end_at"):
        cursor = structured_query.end_at
        candidates = [
            r for r in candidates if _passes_end_cursor(cursor, _doc_orderby_key(r, orders), orders)
        ]

    # 6. Apply offset
    if structured_query.offset > 0:
        candidates = candidates[structured_query.offset :]

    # 7. Apply limit
    if structured_query.HasField("limit"):
        n = structured_query.limit.value
        if n >= 0:
            candidates = candidates[:n]

    return candidates
