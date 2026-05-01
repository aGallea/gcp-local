from datetime import UTC, datetime

import pytest

from gcp_local.services.firestore.errors import DocumentNotFound
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.storage import InMemoryStorage

P, DB = "p1", "(default)"


def _doc(path: str, fields: dict | None = None, version: int = 1) -> DocumentRecord:
    now = datetime(2026, 5, 1, tzinfo=UTC)
    return DocumentRecord(P, DB, path, fields or {"x": 1}, now, now, version)


@pytest.mark.asyncio
async def test_put_and_get_round_trip():
    s = InMemoryStorage()
    rec = _doc("users/alice")
    await s.put_document(rec)
    fetched = await s.get_document(P, DB, "users/alice")
    assert fetched == rec


@pytest.mark.asyncio
async def test_get_missing_raises():
    s = InMemoryStorage()
    with pytest.raises(DocumentNotFound):
        await s.get_document(P, DB, "users/nope")


@pytest.mark.asyncio
async def test_delete_removes():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice"))
    await s.delete_document(P, DB, "users/alice")
    with pytest.raises(DocumentNotFound):
        await s.get_document(P, DB, "users/alice")


@pytest.mark.asyncio
async def test_databases_isolated():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice"))
    now = datetime(2026, 5, 1, tzinfo=UTC)
    rec_other = DocumentRecord(P, "staging", "users/alice", {"x": 99}, now, now, 1)
    await s.put_document(rec_other)
    a = await s.get_document(P, DB, "users/alice")
    b = await s.get_document(P, "staging", "users/alice")
    assert a.fields == {"x": 1}
    assert b.fields == {"x": 99}


@pytest.mark.asyncio
async def test_next_version_monotonic_per_database():
    s = InMemoryStorage()
    v1 = await s.next_version(P, DB)
    v2 = await s.next_version(P, DB)
    v3 = await s.next_version(P, "staging")
    assert v2 == v1 + 1
    assert v3 == 1  # independent counter per database


@pytest.mark.asyncio
async def test_iter_collection_returns_only_direct_children():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice"))
    await s.put_document(_doc("users/bob"))
    await s.put_document(_doc("users/alice/posts/p1"))  # subcollection — excluded
    docs = [d async for d in s.iter_collection(P, DB, "users", all_descendants=False)]
    assert sorted(d.path for d in docs) == ["users/alice", "users/bob"]


@pytest.mark.asyncio
async def test_iter_collection_group_finds_all_descendants():
    s = InMemoryStorage()
    await s.put_document(_doc("users/alice/posts/p1"))
    await s.put_document(_doc("teams/eng/posts/q1"))
    await s.put_document(_doc("users/alice"))  # not a "posts" doc
    docs = [d async for d in s.iter_collection(P, DB, "posts", all_descendants=True)]
    assert sorted(d.path for d in docs) == ["teams/eng/posts/q1", "users/alice/posts/p1"]


@pytest.mark.asyncio
async def test_lock_serializes_per_database():
    s = InMemoryStorage()
    async with s.lock(P, DB):
        # Smoke-test: the context manager returns cleanly.
        pass


@pytest.mark.asyncio
async def test_snapshot_is_noop():
    s = InMemoryStorage()
    result = await s.snapshot(P, DB)
    assert result is None
