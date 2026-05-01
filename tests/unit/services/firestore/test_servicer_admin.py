"""Unit tests for FirestoreAdminServicer — Task 13.

Covers: CreateIndex, GetIndex, ListIndexes, DeleteIndex, and unimplemented stubs.
"""

from __future__ import annotations

import grpc
import pytest

from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2, index_pb2
from gcp_local.services.firestore.servicer import FirestoreAdminServicer
from gcp_local.services.firestore.storage import InMemoryStorage

# ---------------------------------------------------------------------------
# Fake gRPC context
# ---------------------------------------------------------------------------


class _Aborted(Exception):
    pass


class _FakeContext:
    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise _Aborted()


# ---------------------------------------------------------------------------
# Constants and fixture helpers
# ---------------------------------------------------------------------------

PROJECT = "my-project"
DATABASE = "(default)"
COLLECTION_GROUP = "widgets"
PARENT = f"projects/{PROJECT}/databases/{DATABASE}/collectionGroups/{COLLECTION_GROUP}"


def _make_servicer() -> tuple[FirestoreAdminServicer, InMemoryStorage]:
    storage = InMemoryStorage()
    return FirestoreAdminServicer(storage=storage), storage


# ---------------------------------------------------------------------------
# Test 1: CreateIndex returns an Operation with done=True and the index name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_index_returns_done_operation() -> None:
    servicer, _ = _make_servicer()
    req = firestore_admin_pb2.CreateIndexRequest(
        parent=PARENT,
        index=index_pb2.Index(),
    )
    op = await servicer.CreateIndex(req, _FakeContext())

    assert op.done is True
    assert op.name  # non-empty op name
    # The response Any should be unpackable as an Index
    from google.longrunning import operations_pb2  # noqa: F401

    idx = index_pb2.Index()
    assert op.response.Unpack(idx)
    assert idx.name.startswith(PARENT + "/indexes/")


# ---------------------------------------------------------------------------
# Test 2: CreateIndex stores the index so GetIndex retrieves it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_index_then_get_index() -> None:
    servicer, _ = _make_servicer()
    req = firestore_admin_pb2.CreateIndexRequest(
        parent=PARENT,
        index=index_pb2.Index(),
    )
    op = await servicer.CreateIndex(req, _FakeContext())

    packed_idx = index_pb2.Index()
    op.response.Unpack(packed_idx)
    index_name = packed_idx.name

    get_req = firestore_admin_pb2.GetIndexRequest(name=index_name)
    retrieved = await servicer.GetIndex(get_req, _FakeContext())

    assert retrieved.name == index_name
    assert retrieved.state == index_pb2.Index.READY


# ---------------------------------------------------------------------------
# Test 3: GetIndex on a missing name → NOT_FOUND
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_index_missing_not_found() -> None:
    servicer, _ = _make_servicer()
    fake_name = f"{PARENT}/indexes/doesnotexist0000"
    req = firestore_admin_pb2.GetIndexRequest(name=fake_name)
    ctx = _FakeContext()

    with pytest.raises(_Aborted):
        await servicer.GetIndex(req, ctx)

    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


# ---------------------------------------------------------------------------
# Test 4: ListIndexes returns all created indexes for the parent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_indexes_all() -> None:
    servicer, _ = _make_servicer()
    for _ in range(3):
        await servicer.CreateIndex(
            firestore_admin_pb2.CreateIndexRequest(parent=PARENT, index=index_pb2.Index()),
            _FakeContext(),
        )

    resp = await servicer.ListIndexes(
        firestore_admin_pb2.ListIndexesRequest(parent=PARENT), _FakeContext()
    )

    assert len(resp.indexes) == 3
    assert resp.next_page_token == ""
    for idx in resp.indexes:
        assert idx.name.startswith(PARENT + "/indexes/")


# ---------------------------------------------------------------------------
# Test 5: ListIndexes paginates correctly with page_size < total
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_indexes_pagination() -> None:
    servicer, _ = _make_servicer()
    for _ in range(5):
        await servicer.CreateIndex(
            firestore_admin_pb2.CreateIndexRequest(parent=PARENT, index=index_pb2.Index()),
            _FakeContext(),
        )

    # First page: 2 items
    page1 = await servicer.ListIndexes(
        firestore_admin_pb2.ListIndexesRequest(parent=PARENT, page_size=2),
        _FakeContext(),
    )
    assert len(page1.indexes) == 2
    assert page1.next_page_token != ""

    # Second page: next 2 items
    page2 = await servicer.ListIndexes(
        firestore_admin_pb2.ListIndexesRequest(
            parent=PARENT, page_size=2, page_token=page1.next_page_token
        ),
        _FakeContext(),
    )
    assert len(page2.indexes) == 2
    assert page2.next_page_token != ""

    # Third page: last 1 item
    page3 = await servicer.ListIndexes(
        firestore_admin_pb2.ListIndexesRequest(
            parent=PARENT, page_size=2, page_token=page2.next_page_token
        ),
        _FakeContext(),
    )
    assert len(page3.indexes) == 1
    assert page3.next_page_token == ""

    # All names are distinct and cover all 5
    all_names = {i.name for i in list(page1.indexes) + list(page2.indexes) + list(page3.indexes)}
    assert len(all_names) == 5


# ---------------------------------------------------------------------------
# Test 6: DeleteIndex removes the record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_index_removes_record() -> None:
    servicer, _ = _make_servicer()
    op = await servicer.CreateIndex(
        firestore_admin_pb2.CreateIndexRequest(parent=PARENT, index=index_pb2.Index()),
        _FakeContext(),
    )
    packed_idx = index_pb2.Index()
    op.response.Unpack(packed_idx)
    index_name = packed_idx.name

    # Confirm it exists
    retrieved = await servicer.GetIndex(
        firestore_admin_pb2.GetIndexRequest(name=index_name), _FakeContext()
    )
    assert retrieved.name == index_name

    # Delete it
    await servicer.DeleteIndex(
        firestore_admin_pb2.DeleteIndexRequest(name=index_name), _FakeContext()
    )

    # Now GetIndex should return NOT_FOUND
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetIndex(firestore_admin_pb2.GetIndexRequest(name=index_name), ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


# ---------------------------------------------------------------------------
# Test 7: ExportDocuments → UNIMPLEMENTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_documents_unimplemented() -> None:
    servicer, _ = _make_servicer()
    ctx = _FakeContext()
    req = firestore_admin_pb2.ExportDocumentsRequest(
        name=f"projects/{PROJECT}/databases/{DATABASE}"
    )
    with pytest.raises(_Aborted):
        await servicer.ExportDocuments(req, ctx)

    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.UNIMPLEMENTED


# ---------------------------------------------------------------------------
# Test 8: CreateDatabase → UNIMPLEMENTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_database_unimplemented() -> None:
    servicer, _ = _make_servicer()
    ctx = _FakeContext()
    req = firestore_admin_pb2.CreateDatabaseRequest(
        parent=f"projects/{PROJECT}",
    )
    with pytest.raises(_Aborted):
        await servicer.CreateDatabase(req, ctx)

    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.UNIMPLEMENTED


# ---------------------------------------------------------------------------
# Test 9: DeleteIndex on missing name is a no-op (no error)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_index_missing_is_noop() -> None:
    servicer, _ = _make_servicer()
    fake_name = f"{PARENT}/indexes/ghostindex0000000"
    ctx = _FakeContext()
    result = await servicer.DeleteIndex(firestore_admin_pb2.DeleteIndexRequest(name=fake_name), ctx)
    # Should not abort; returns Empty
    assert ctx.aborted is None
    assert result is not None


# ---------------------------------------------------------------------------
# Test 10: ListIndexes for a different collection group does not include indexes
#          from a different group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_indexes_scoped_to_parent() -> None:
    servicer, _ = _make_servicer()
    other_parent = f"projects/{PROJECT}/databases/{DATABASE}/collectionGroups/gadgets"

    # Create 2 indexes under PARENT and 1 under other_parent
    for _ in range(2):
        await servicer.CreateIndex(
            firestore_admin_pb2.CreateIndexRequest(parent=PARENT, index=index_pb2.Index()),
            _FakeContext(),
        )
    await servicer.CreateIndex(
        firestore_admin_pb2.CreateIndexRequest(parent=other_parent, index=index_pb2.Index()),
        _FakeContext(),
    )

    resp_main = await servicer.ListIndexes(
        firestore_admin_pb2.ListIndexesRequest(parent=PARENT), _FakeContext()
    )
    resp_other = await servicer.ListIndexes(
        firestore_admin_pb2.ListIndexesRequest(parent=other_parent), _FakeContext()
    )

    assert len(resp_main.indexes) == 2
    assert len(resp_other.indexes) == 1
