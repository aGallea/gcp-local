"""Tests for cursor pipeline (start_at, start_after, end_at, end_before) in run_query."""

import asyncio
from datetime import UTC, datetime

from google.protobuf import wrappers_pb2

from gcp_local.generated.google.firestore.v1 import query_pb2
from gcp_local.services.firestore.engine.query import run_query
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.storage import InMemoryStorage
from gcp_local.services.firestore.values import to_proto

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
_PROJ = "proj"
_DB = "(default)"

_DIR = query_pb2.StructuredQuery.Direction


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


def _cursor(*values, before: bool) -> query_pb2.Cursor:
    return query_pb2.Cursor(
        values=[to_proto(v) for v in values],
        before=before,
    )


def _make_query(
    collection_id: str = "col",
    order_by: list | None = None,
    start_at: query_pb2.Cursor | None = None,
    end_at: query_pb2.Cursor | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> query_pb2.StructuredQuery:
    q = query_pb2.StructuredQuery()
    sel = query_pb2.StructuredQuery.CollectionSelector(
        collection_id=collection_id, all_descendants=False
    )
    getattr(q, "from").append(sel)
    if order_by:
        q.order_by.extend(order_by)
    if start_at is not None:
        q.start_at.CopyFrom(start_at)
    if end_at is not None:
        q.end_at.CopyFrom(end_at)
    if limit is not None:
        q.limit.CopyFrom(wrappers_pb2.Int32Value(value=limit))
    if offset:
        q.offset = offset
    return q


# ---------------------------------------------------------------------------
# Seed data: docs with score 10, 20, 30, 40, 50
# ---------------------------------------------------------------------------

_SCORES = [10, 20, 30, 40, 50]
_IDS = ["a", "b", "c", "d", "e"]


def _make_recs() -> list[DocumentRecord]:
    return [_rec(doc_id, {"score": s}) for doc_id, s in zip(_IDS, _SCORES, strict=False)]


async def _run_with_cursors(
    start_cursor: query_pb2.Cursor | None = None,
    end_cursor: query_pb2.Cursor | None = None,
) -> list[int]:
    storage = InMemoryStorage()
    await _seed(storage, *_make_recs())
    q = _make_query(
        order_by=[_order("score", _DIR.ASCENDING)],
        start_at=start_cursor,
        end_at=end_cursor,
    )
    result = await run_query(storage, _PROJ, _DB, q)
    return [r.fields["score"] for r in result]


# ---------------------------------------------------------------------------
# start_at (inclusive: before=True on start cursor)
# ---------------------------------------------------------------------------


class TestStartAt:
    def test_start_at_inclusive(self):
        """start_at with cursor value 20, before=True → include doc with score 20."""
        scores = asyncio.run(_run_with_cursors(start_cursor=_cursor(20, before=True)))
        assert scores == [20, 30, 40, 50]

    def test_start_at_first_doc(self):
        """Cursor at the very first value includes everything."""
        scores = asyncio.run(_run_with_cursors(start_cursor=_cursor(10, before=True)))
        assert scores == [10, 20, 30, 40, 50]

    def test_start_at_beyond_last(self):
        """Cursor beyond last doc returns empty."""
        scores = asyncio.run(_run_with_cursors(start_cursor=_cursor(60, before=True)))
        assert scores == []


# ---------------------------------------------------------------------------
# start_after (exclusive: before=False on start cursor)
# ---------------------------------------------------------------------------


class TestStartAfter:
    def test_start_after_exclusive(self):
        """start_after cursor value 20, before=False → exclude doc with score 20."""
        scores = asyncio.run(_run_with_cursors(start_cursor=_cursor(20, before=False)))
        assert scores == [30, 40, 50]

    def test_start_after_last_doc(self):
        """Cursor after last doc returns empty."""
        scores = asyncio.run(_run_with_cursors(start_cursor=_cursor(50, before=False)))
        assert scores == []


# ---------------------------------------------------------------------------
# end_before (exclusive: before=True on end cursor)
# ---------------------------------------------------------------------------


class TestEndBefore:
    def test_end_before_exclusive(self):
        """end_before cursor value 30, before=True → exclude doc with score 30."""
        scores = asyncio.run(_run_with_cursors(end_cursor=_cursor(30, before=True)))
        assert scores == [10, 20]

    def test_end_before_first_doc(self):
        """Cursor before first doc returns empty."""
        scores = asyncio.run(_run_with_cursors(end_cursor=_cursor(10, before=True)))
        assert scores == []


# ---------------------------------------------------------------------------
# end_at (inclusive: before=False on end cursor)
# ---------------------------------------------------------------------------


class TestEndAt:
    def test_end_at_inclusive(self):
        """end_at cursor value 30, before=False → include doc with score 30."""
        scores = asyncio.run(_run_with_cursors(end_cursor=_cursor(30, before=False)))
        assert scores == [10, 20, 30]

    def test_end_at_last_doc(self):
        """Cursor at last doc includes everything."""
        scores = asyncio.run(_run_with_cursors(end_cursor=_cursor(50, before=False)))
        assert scores == [10, 20, 30, 40, 50]


# ---------------------------------------------------------------------------
# Combined start + end
# ---------------------------------------------------------------------------


class TestStartAndEnd:
    def test_window_inclusive_inclusive(self):
        """start_at=20 (inclusive), end_at=40 (inclusive)."""
        scores = asyncio.run(
            _run_with_cursors(
                start_cursor=_cursor(20, before=True),
                end_cursor=_cursor(40, before=False),
            )
        )
        assert scores == [20, 30, 40]

    def test_window_exclusive_exclusive(self):
        """start_after=10, end_before=40."""
        scores = asyncio.run(
            _run_with_cursors(
                start_cursor=_cursor(10, before=False),
                end_cursor=_cursor(40, before=True),
            )
        )
        assert scores == [20, 30]


# ---------------------------------------------------------------------------
# Partial cursor (fewer values than orderBy fields)
# ---------------------------------------------------------------------------


class TestPartialCursor:
    def test_partial_cursor_start_at(self):
        """OrderBy has 2 fields, cursor has 1 value. Ties on prefix are included (before=True)."""
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"score": 10, "rank": 1}),
            _rec("b", {"score": 10, "rank": 2}),
            _rec("c", {"score": 20, "rank": 1}),
            _rec("d", {"score": 20, "rank": 2}),
        ]

        async def run():
            await _seed(storage, *recs)
            # Order by score ASC, rank ASC. Cursor on score=20 only (partial).
            # before=True → include ties on the prefix (score=20 included)
            cursor = _cursor(20, before=True)
            q = _make_query(
                order_by=[_order("score"), _order("rank")],
                start_at=cursor,
            )
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.fields["score"] for r in result]

        scores = asyncio.run(run())
        # score=20 docs are included (partial cursor is inclusive on prefix)
        assert 20 in scores
        assert 10 not in scores

    def test_partial_cursor_end_before(self):
        """Partial end cursor: end_before score=20 excludes all score=20 docs."""
        storage = InMemoryStorage()
        recs = [
            _rec("a", {"score": 10, "rank": 1}),
            _rec("b", {"score": 10, "rank": 2}),
            _rec("c", {"score": 20, "rank": 1}),
        ]

        async def run():
            await _seed(storage, *recs)
            cursor = _cursor(20, before=True)  # end_before semantics
            q = _make_query(
                order_by=[_order("score"), _order("rank")],
                end_at=cursor,
            )
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.fields["score"] for r in result]

        scores = asyncio.run(run())
        assert all(s == 10 for s in scores)
        assert len(scores) == 2


# ---------------------------------------------------------------------------
# limit
# ---------------------------------------------------------------------------


class TestLimit:
    def test_limit_truncates(self):
        storage = InMemoryStorage()
        recs = _make_recs()

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("score")], limit=3)
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.fields["score"] for r in result]

        scores = asyncio.run(run())
        assert scores == [10, 20, 30]

    def test_limit_larger_than_result_set(self):
        storage = InMemoryStorage()
        recs = _make_recs()

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("score")], limit=100)
            result = await run_query(storage, _PROJ, _DB, q)
            return len(result)

        count = asyncio.run(run())
        assert count == 5


# ---------------------------------------------------------------------------
# offset
# ---------------------------------------------------------------------------


class TestOffset:
    def test_offset_skips(self):
        storage = InMemoryStorage()
        recs = _make_recs()

        async def run():
            await _seed(storage, *recs)
            q = _make_query(order_by=[_order("score")], offset=2)
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.fields["score"] for r in result]

        scores = asyncio.run(run())
        assert scores == [30, 40, 50]
