"""Tests for orderBy pipeline in run_query."""

import asyncio
from datetime import UTC, datetime

from gcp_local.generated.google.firestore.v1 import query_pb2
from gcp_local.services.firestore.engine.query import run_query
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.storage import InMemoryStorage
from gcp_local.services.firestore.values import to_proto

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
_PROJ = "proj"
_DB = "(default)"

_DIR = query_pb2.StructuredQuery.Direction
_FF = query_pb2.StructuredQuery.FieldFilter
_OP = query_pb2.StructuredQuery.FieldFilter.Operator


def _rec(doc_id: str, fields: dict, collection: str = "col") -> DocumentRecord:
    return DocumentRecord(
        project=_PROJ,
        database=_DB,
        path=f"{collection}/{doc_id}",
        fields=fields,
        create_time=_NOW,
        update_time=_NOW,
        version=1,
    )


async def _seed(storage: InMemoryStorage, *recs: DocumentRecord) -> None:
    for r in recs:
        await storage.put_document(r)


def _order(field_path: str, direction=_DIR.ASCENDING) -> query_pb2.StructuredQuery.Order:
    return query_pb2.StructuredQuery.Order(
        field=query_pb2.StructuredQuery.FieldReference(field_path=field_path),
        direction=direction,
    )


def _make_query(
    collection_id: str = "col",
    all_descendants: bool = False,
    order_by: list | None = None,
    where: query_pb2.StructuredQuery.Filter | None = None,
) -> query_pb2.StructuredQuery:
    """Build a StructuredQuery. Uses getattr to set the 'from' field (Python reserved word)."""
    q = query_pb2.StructuredQuery()
    sel = query_pb2.StructuredQuery.CollectionSelector(
        collection_id=collection_id, all_descendants=all_descendants
    )
    getattr(q, "from").append(sel)
    if order_by:
        q.order_by.extend(order_by)
    if where is not None:
        q.where.CopyFrom(where)
    return q


def _field_filter(field_path: str, op, value) -> query_pb2.StructuredQuery.Filter:
    return query_pb2.StructuredQuery.Filter(
        field_filter=_FF(
            field=query_pb2.StructuredQuery.FieldReference(field_path=field_path),
            op=op,
            value=to_proto(value),
        )
    )


# ---------------------------------------------------------------------------
# Single-field ASC
# ---------------------------------------------------------------------------


class TestOrderByAsc:
    def test_single_field_asc(self):
        storage = InMemoryStorage()
        recs = [_rec("c", {"score": 30}), _rec("a", {"score": 10}), _rec("b", {"score": 20})]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("score", _DIR.ASCENDING)])
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        assert paths == ["col/a", "col/b", "col/c"]

    def test_single_field_desc(self):
        storage = InMemoryStorage()
        recs = [_rec("a", {"score": 10}), _rec("b", {"score": 20}), _rec("c", {"score": 30})]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("score", _DIR.DESCENDING)])
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        assert paths == ["col/c", "col/b", "col/a"]


# ---------------------------------------------------------------------------
# Multi-field orderBy
# ---------------------------------------------------------------------------


class TestMultiFieldOrderBy:
    def test_multi_field_sort(self):
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"score": 10, "name": "zara"}),
            _rec("b", {"score": 10, "name": "alice"}),
            _rec("c", {"score": 20, "name": "bob"}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(
                order_by=[
                    _order("score", _DIR.ASCENDING),
                    _order("name", _DIR.ASCENDING),
                ]
            )
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        # score=10 alice, score=10 zara, score=20 bob
        assert paths == ["col/b", "col/a", "col/c"]

    def test_multi_field_mixed_directions(self):
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"score": 10, "name": "alice"}),
            _rec("b", {"score": 10, "name": "zara"}),
            _rec("c", {"score": 20, "name": "bob"}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(
                order_by=[
                    _order("score", _DIR.DESCENDING),
                    _order("name", _DIR.ASCENDING),
                ]
            )
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        # score DESC: 20 bob, then 10 alice/zara ASC
        assert paths == ["col/c", "col/a", "col/b"]


# ---------------------------------------------------------------------------
# Implicit __name__ tiebreak
# ---------------------------------------------------------------------------


class TestImplicitNameTiebreak:
    def test_name_tiebreak_asc(self):
        """When orderBy has no explicit __name__, __name__ ASC is the tiebreak."""
        storage = InMemoryStorage()
        recs = [
            _rec("z", {"score": 10}),
            _rec("a", {"score": 10}),
            _rec("m", {"score": 10}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("score", _DIR.ASCENDING)])
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        # same score → tiebreak by __name__ ASC
        assert paths == ["col/a", "col/m", "col/z"]

    def test_name_tiebreak_follows_last_direction(self):
        """When last explicit orderBy is DESC, implicit __name__ is also DESC."""
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"score": 10}),
            _rec("m", {"score": 10}),
            _rec("z", {"score": 10}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("score", _DIR.DESCENDING)])
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        # same score DESC → tiebreak by __name__ DESC
        assert paths == ["col/z", "col/m", "col/a"]


# ---------------------------------------------------------------------------
# Implicit orderBy on inequality field
# ---------------------------------------------------------------------------


class TestImplicitOrderByInequalityField:
    def test_inequality_field_prepended_to_orderby(self):
        """where score > 5 with orderBy name should add implicit orderBy score ASC first."""
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"score": 10, "name": "charlie"}),
            _rec("b", {"score": 20, "name": "alice"}),
            _rec("c", {"score": 15, "name": "bob"}),
        ]

        async def run():
            await _seed(storage, *recs)
            where = _field_filter("score", _OP.GREATER_THAN, 5)
            q = _make_query(
                order_by=[_order("name", _DIR.ASCENDING)],
                where=where,
            )
            result = await run_query(storage, _PROJ, _DB, q)
            return [(r.path, r.fields["score"]) for r in result]

        result = asyncio.run(run())
        # implicit orderBy score ASC first, then name ASC
        scores = [s for _, s in result]
        assert scores == sorted(scores)

    def test_no_implicit_orderby_when_equality_only(self):
        """EQUAL filter does NOT add an implicit orderBy."""
        storage = InMemoryStorage()
        recs = [
            _rec("z", {"score": 10, "name": "zara"}),
            _rec("a", {"score": 10, "name": "alice"}),
        ]

        async def run():
            await _seed(storage, *recs)
            where = _field_filter("score", _OP.EQUAL, 10)
            q = _make_query(
                order_by=[_order("name", _DIR.ASCENDING)],
                where=where,
            )
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.fields["name"] for r in result]

        result = asyncio.run(run())
        assert result == ["alice", "zara"]


# ---------------------------------------------------------------------------
# Type-aware ordering: NaN smallest
# ---------------------------------------------------------------------------


class TestTypeAwareOrdering:
    def test_nan_sorts_smallest(self):
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"val": 5.0}),
            _rec("b", {"val": float("nan")}),
            _rec("c", {"val": 1.0}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("val", _DIR.ASCENDING)])
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        # NaN is smallest among numbers
        assert paths[0] == "col/b"

    def test_mixed_types_ordered_by_bucket(self):
        """null < bool < number per type ordering."""
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"val": 1}),
            _rec("b", {"val": None}),
            _rec("c", {"val": True}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("val", _DIR.ASCENDING)])
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        # null < bool < number
        assert paths == ["col/b", "col/c", "col/a"]
