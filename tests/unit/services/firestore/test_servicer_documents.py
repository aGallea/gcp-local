"""Unit tests for Firestore document CRUD RPCs (Task 6)."""

from __future__ import annotations

from datetime import UTC, datetime

import grpc
import pytest
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.firestore.v1 import document_pb2, firestore_pb2
from gcp_local.services.firestore.servicer import FirestoreServicer
from gcp_local.services.firestore.storage import InMemoryStorage

# ---------------------------------------------------------------------------
# Fake gRPC context
# ---------------------------------------------------------------------------


class _Aborted(Exception):
    pass


class _FakeContext:
    """Minimal stand-in for grpc.aio.ServicerContext — captures abort calls."""

    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise _Aborted()

    def HasField(self, name: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT = "my-project"
DATABASE = "(default)"
DB_ROOT = f"projects/{PROJECT}/databases/{DATABASE}"
DOC_ROOT = f"{DB_ROOT}/documents"


def _make_servicer() -> tuple[FirestoreServicer, InMemoryStorage]:
    storage = InMemoryStorage()
    servicer = FirestoreServicer(storage=storage, state_hub=StateHub())
    return servicer, storage


def _str_val(s: str) -> document_pb2.Value:
    return document_pb2.Value(string_value=s)


def _doc_with_fields(**kwargs: str) -> document_pb2.Document:
    return document_pb2.Document(fields={k: _str_val(v) for k, v in kwargs.items()})


async def _create(
    servicer: FirestoreServicer,
    collection: str,
    doc_id: str,
    **fields: str,
) -> document_pb2.Document:
    req = firestore_pb2.CreateDocumentRequest(
        parent=DOC_ROOT,
        collection_id=collection,
        document_id=doc_id,
        document=_doc_with_fields(**fields),
    )
    return await servicer.CreateDocument(req, _FakeContext())


# ---------------------------------------------------------------------------
# Test 1: GetDocument missing → NOT_FOUND
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_document_missing_returns_not_found() -> None:
    servicer, _ = _make_servicer()
    req = firestore_pb2.GetDocumentRequest(name=f"{DOC_ROOT}/users/nonexistent")
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetDocument(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


# ---------------------------------------------------------------------------
# Test 2: GetDocument found → correct fields, timestamps, name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_document_found_returns_document() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "users", "alice", name="Alice", age="30")

    req = firestore_pb2.GetDocumentRequest(name=f"{DOC_ROOT}/users/alice")
    doc = await servicer.GetDocument(req, _FakeContext())

    assert doc.name == f"{DOC_ROOT}/users/alice"
    assert doc.fields["name"].string_value == "Alice"
    assert doc.fields["age"].string_value == "30"
    # create_time and update_time should be set (non-zero epoch)
    assert doc.create_time.seconds > 0
    assert doc.update_time.seconds > 0
    assert doc.create_time == doc.update_time


# ---------------------------------------------------------------------------
# Test 3: CreateDocument with doc_id → creates; duplicate → ALREADY_EXISTS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_document_duplicate_returns_already_exists() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "users", "bob", name="Bob")

    req = firestore_pb2.CreateDocumentRequest(
        parent=DOC_ROOT,
        collection_id="users",
        document_id="bob",
        document=_doc_with_fields(name="Bob2"),
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.CreateDocument(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.ALREADY_EXISTS


# ---------------------------------------------------------------------------
# Test 4: CreateDocument empty document_id → mints 20-char ID; GetDocument finds it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_document_mints_id_when_empty() -> None:
    servicer, _ = _make_servicer()
    req = firestore_pb2.CreateDocumentRequest(
        parent=DOC_ROOT,
        collection_id="items",
        document_id="",
        document=_doc_with_fields(label="widget"),
    )
    doc = await servicer.CreateDocument(req, _FakeContext())

    # Minted ID is embedded in the name after the collection
    assert doc.name.startswith(f"{DOC_ROOT}/items/")
    doc_id = doc.name.split("/")[-1]
    assert len(doc_id) == 20

    # GetDocument should find it
    get_req = firestore_pb2.GetDocumentRequest(name=doc.name)
    fetched = await servicer.GetDocument(get_req, _FakeContext())
    assert fetched.fields["label"].string_value == "widget"


# ---------------------------------------------------------------------------
# Test 5: UpdateDocument no mask → replaces entire fields dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_document_no_mask_replaces_fields() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "users", "carol", name="Carol", role="admin")

    update_req = firestore_pb2.UpdateDocumentRequest(
        document=document_pb2.Document(
            name=f"{DOC_ROOT}/users/carol",
            fields={"email": _str_val("carol@example.com")},
        )
        # no update_mask
    )
    updated = await servicer.UpdateDocument(update_req, _FakeContext())

    assert "email" in updated.fields
    assert "name" not in updated.fields
    assert "role" not in updated.fields


# ---------------------------------------------------------------------------
# Test 6: UpdateDocument with update_mask → merges only listed fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_document_with_mask_merges_fields() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "users", "dave", name="Dave", role="user", score="100")

    from gcp_local.generated.google.firestore.v1.common_pb2 import DocumentMask

    update_req = firestore_pb2.UpdateDocumentRequest(
        document=document_pb2.Document(
            name=f"{DOC_ROOT}/users/dave",
            fields={"role": _str_val("admin"), "score": _str_val("200")},
        ),
        update_mask=DocumentMask(field_paths=["role"]),
    )
    updated = await servicer.UpdateDocument(update_req, _FakeContext())

    # 'role' updated, 'name' and 'score' untouched
    assert updated.fields["role"].string_value == "admin"
    assert updated.fields["name"].string_value == "Dave"
    assert updated.fields["score"].string_value == "100"


# ---------------------------------------------------------------------------
# Test 7: UpdateDocument current_document.exists=true on missing doc → FAILED_PRECONDITION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_document_exists_precondition_on_missing_fails() -> None:
    servicer, _ = _make_servicer()

    from gcp_local.generated.google.firestore.v1.common_pb2 import Precondition

    req = firestore_pb2.UpdateDocumentRequest(
        document=document_pb2.Document(
            name=f"{DOC_ROOT}/users/ghost",
            fields={"x": _str_val("y")},
        ),
        current_document=Precondition(exists=True),
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.UpdateDocument(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION


# ---------------------------------------------------------------------------
# Test 8: UpdateDocument with stale update_time precondition → FAILED_PRECONDITION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_document_stale_update_time_fails() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "users", "eve", name="Eve")

    from gcp_local.generated.google.firestore.v1.common_pb2 import Precondition

    stale_ts = Timestamp()
    stale_ts.FromDatetime(datetime(2000, 1, 1, tzinfo=UTC))

    req = firestore_pb2.UpdateDocumentRequest(
        document=document_pb2.Document(
            name=f"{DOC_ROOT}/users/eve",
            fields={"name": _str_val("Eve Updated")},
        ),
        current_document=Precondition(update_time=stale_ts),
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.UpdateDocument(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION


# ---------------------------------------------------------------------------
# Test 9: DeleteDocument removes the doc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_document_removes_doc() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "users", "frank", name="Frank")

    del_req = firestore_pb2.DeleteDocumentRequest(name=f"{DOC_ROOT}/users/frank")
    result = await servicer.DeleteDocument(del_req, _FakeContext())

    from google.protobuf import empty_pb2

    assert isinstance(result, empty_pb2.Empty)

    # Subsequent get should be NOT_FOUND
    get_req = firestore_pb2.GetDocumentRequest(name=f"{DOC_ROOT}/users/frank")
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetDocument(get_req, ctx)
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


# ---------------------------------------------------------------------------
# Test 10: DeleteDocument with current_document.exists=true on missing → FAILED_PRECONDITION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_document_exists_precondition_on_missing_fails() -> None:
    servicer, _ = _make_servicer()

    from gcp_local.generated.google.firestore.v1.common_pb2 import Precondition

    req = firestore_pb2.DeleteDocumentRequest(
        name=f"{DOC_ROOT}/users/nobody",
        current_document=Precondition(exists=True),
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.DeleteDocument(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION


# ---------------------------------------------------------------------------
# Test 11: BatchGetDocuments yields found + missing mix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_get_documents_found_and_missing() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "docs", "a", val="A")
    await _create(servicer, "docs", "b", val="B")

    req = firestore_pb2.BatchGetDocumentsRequest(
        database=DB_ROOT,
        documents=[
            f"{DOC_ROOT}/docs/a",
            f"{DOC_ROOT}/docs/missing1",
            f"{DOC_ROOT}/docs/b",
        ],
    )
    responses = []
    async for resp in servicer.BatchGetDocuments(req, _FakeContext()):
        responses.append(resp)

    # Last response has only read_time set
    last = responses[-1]
    assert last.read_time.seconds > 0

    result_type = [r.WhichOneof("result") for r in responses[:-1]]
    assert result_type.count("found") == 2
    assert result_type.count("missing") == 1

    # The missing one should carry the correct name
    missing_responses = [r for r in responses if r.WhichOneof("result") == "missing"]
    assert missing_responses[0].missing == f"{DOC_ROOT}/docs/missing1"


# ---------------------------------------------------------------------------
# Test 12: ListDocuments paginates with page_size + page_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_paginates() -> None:
    servicer, _ = _make_servicer()
    for name in ["alpha", "beta", "gamma", "delta"]:
        await _create(servicer, "items", name, label=name)

    req1 = firestore_pb2.ListDocumentsRequest(
        parent=DOC_ROOT,
        collection_id="items",
        page_size=2,
    )
    resp1 = await servicer.ListDocuments(req1, _FakeContext())
    assert len(resp1.documents) == 2
    assert resp1.next_page_token != ""

    req2 = firestore_pb2.ListDocumentsRequest(
        parent=DOC_ROOT,
        collection_id="items",
        page_size=2,
        page_token=resp1.next_page_token,
    )
    resp2 = await servicer.ListDocuments(req2, _FakeContext())
    assert len(resp2.documents) == 2
    assert resp2.next_page_token == ""

    # All 4 docs retrieved without overlap
    names1 = {d.name for d in resp1.documents}
    names2 = {d.name for d in resp2.documents}
    assert names1.isdisjoint(names2)
    assert len(names1 | names2) == 4


# ---------------------------------------------------------------------------
# Test 13: ListCollectionIds returns distinct sorted collection IDs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_collection_ids_returns_sorted_distinct() -> None:
    servicer, _ = _make_servicer()
    # Create docs in different collections under the root
    await _create(servicer, "users", "u1", x="1")
    await _create(servicer, "users", "u2", x="2")
    await _create(servicer, "orders", "o1", x="3")
    await _create(servicer, "products", "p1", x="4")

    req = firestore_pb2.ListCollectionIdsRequest(parent=DOC_ROOT)
    resp = await servicer.ListCollectionIds(req, _FakeContext())

    assert list(resp.collection_ids) == sorted(resp.collection_ids)
    assert set(resp.collection_ids) == {"users", "orders", "products"}
