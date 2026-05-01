"""Tests for collection-group queries (all_descendants=True) in run_query."""

import asyncio
from datetime import UTC, datetime

from gcp_local.generated.google.firestore.v1 import query_pb2
from gcp_local.services.firestore.engine.query import run_query
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.storage import InMemoryStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
_PROJ = "proj"
_DB = "(default)"


def _rec(path: str, fields: dict) -> DocumentRecord:
    return DocumentRecord(
        project=_PROJ,
        database=_DB,
        path=path,
        fields=fields,
        create_time=_NOW,
        update_time=_NOW,
        version=1,
    )


async def _seed(storage: InMemoryStorage, *recs: DocumentRecord) -> None:
    for r in recs:
        await storage.put_document(r)


def _cg_query(collection_id: str) -> query_pb2.StructuredQuery:
    """Collection-group query (all_descendants=True)."""
    q = query_pb2.StructuredQuery()
    sel = query_pb2.StructuredQuery.CollectionSelector(
        collection_id=collection_id, all_descendants=True
    )
    (getattr(q, "from", None) or q.from_).append(sel)
    return q


def _shallow_query(collection_id: str) -> query_pb2.StructuredQuery:
    """Shallow collection query (all_descendants=False)."""
    q = query_pb2.StructuredQuery()
    sel = query_pb2.StructuredQuery.CollectionSelector(
        collection_id=collection_id, all_descendants=False
    )
    (getattr(q, "from", None) or q.from_).append(sel)
    return q


# ---------------------------------------------------------------------------
# Collection-group: all_descendants=True
# ---------------------------------------------------------------------------


class TestCollectionGroup:
    def test_matches_nested_collections(self):
        """all_descendants=True returns docs from deeply nested sub-collections."""
        storage = InMemoryStorage()
        recs = [
            # Top-level "reviews" collection
            _rec("reviews/r1", {"text": "top1"}),
            # Nested under users/u1
            _rec("users/u1/reviews/r2", {"text": "nested1"}),
            # Doubly nested
            _rec("users/u1/orders/o1/reviews/r3", {"text": "nested2"}),
            # Different collection — should NOT appear
            _rec("other/o1", {"text": "irrelevant"}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _cg_query("reviews")
            result = await run_query(storage, _PROJ, _DB, q)
            return sorted(r.path for r in result)

        paths = asyncio.run(run())
        assert "reviews/r1" in paths
        assert "users/u1/reviews/r2" in paths
        assert "users/u1/orders/o1/reviews/r3" in paths
        assert "other/o1" not in paths

    def test_collection_group_excludes_document_id_match(self):
        """A doc whose ID equals the collection_id does not accidentally appear."""
        storage = InMemoryStorage()
        recs = [
            # "reviews" appears as a document ID under "col" — should NOT match
            _rec("col/reviews", {"x": 1}),
            # This one should match
            _rec("reviews/r1", {"x": 2}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _cg_query("reviews")
            result = await run_query(storage, _PROJ, _DB, q)
            return [r.path for r in result]

        paths = asyncio.run(run())
        assert "reviews/r1" in paths
        assert "col/reviews" not in paths

    def test_empty_database_returns_no_results(self):
        storage = InMemoryStorage()

        async def run():
            q = _cg_query("reviews")
            return await run_query(storage, _PROJ, _DB, q)

        result = asyncio.run(run())
        assert result == []


# ---------------------------------------------------------------------------
# Shallow collection query (all_descendants=False)
# ---------------------------------------------------------------------------


class TestShallowCollection:
    def test_top_level_shallow(self):
        """parent_path="" returns only direct children of the top-level collection."""
        storage = InMemoryStorage()
        recs = [
            _rec("col/doc1", {"x": 1}),
            _rec("col/doc2", {"x": 2}),
            # Nested subcollection — should NOT appear
            _rec("col/doc1/sub/s1", {"x": 3}),
            # Different top-level collection
            _rec("other/d1", {"x": 4}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _shallow_query("col")
            result = await run_query(storage, _PROJ, _DB, q)
            return sorted(r.path for r in result)

        paths = asyncio.run(run())
        assert paths == ["col/doc1", "col/doc2"]

    def test_subcollection_shallow(self):
        """parent_path='users/u1' with collection_id='posts' returns direct children only."""
        storage = InMemoryStorage()
        recs = [
            _rec("users/u1/posts/p1", {"title": "first"}),
            _rec("users/u1/posts/p2", {"title": "second"}),
            # Different user — should NOT appear
            _rec("users/u2/posts/p3", {"title": "other"}),
            # Top-level "posts" — should NOT appear
            _rec("posts/p4", {"title": "top-level"}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _shallow_query("posts")
            result = await run_query(storage, _PROJ, _DB, q, parent_path="users/u1")
            return sorted(r.path for r in result)

        paths = asyncio.run(run())
        assert paths == ["users/u1/posts/p1", "users/u1/posts/p2"]

    def test_shallow_does_not_match_nested(self):
        """Shallow query does not match docs that live deeper in the hierarchy."""
        storage = InMemoryStorage()
        recs = [
            _rec("col/doc1/sub/s1", {"x": 1}),
        ]

        async def run():
            await _seed(storage, *recs)
            q = _shallow_query("col")
            result = await run_query(storage, _PROJ, _DB, q)
            return result

        result = asyncio.run(run())
        assert result == []
