"""Unit tests for Firestore transaction state machine (Task 12)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.firestore.v1 import (
    common_pb2,
    document_pb2,
    firestore_pb2,
    write_pb2,
)
from gcp_local.services.firestore.engine.transactions import (
    TransactionTtlSweeper,
    begin_transaction,
)
from gcp_local.services.firestore.servicer import FirestoreServicer
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

    def HasField(self, name: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Constants & helpers
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


async def _create_doc(
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


def _make_update_write(doc_name: str, **fields: str) -> write_pb2.Write:
    doc = document_pb2.Document(
        name=doc_name,
        fields={k: _str_val(v) for k, v in fields.items()},
    )
    return write_pb2.Write(update=doc)


# ---------------------------------------------------------------------------
# Test 1: BeginTransaction returns a non-empty bytes token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_transaction_returns_token() -> None:
    servicer, _ = _make_servicer()
    req = firestore_pb2.BeginTransactionRequest(database=DB_ROOT)
    ctx = _FakeContext()
    resp = await servicer.BeginTransaction(req, ctx)
    assert ctx.aborted is None
    assert resp.transaction  # must be non-empty bytes
    # Token must be ASCII-decodable
    txn_id = resp.transaction.decode("ascii")
    assert len(txn_id) > 0


# ---------------------------------------------------------------------------
# Test 2: Read inside txn records read_set; commit with no writes succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_inside_transaction_records_read_set_and_commit_succeeds() -> None:
    servicer, storage = _make_servicer()

    # Create a document first (outside any txn)
    await _create_doc(servicer, "users", "alice", name="Alice")

    # Begin transaction
    begin_req = firestore_pb2.BeginTransactionRequest(database=DB_ROOT)
    begin_resp = await servicer.BeginTransaction(begin_req, _FakeContext())
    txn_token = begin_resp.transaction

    # Read the document inside the transaction
    get_req = firestore_pb2.GetDocumentRequest(
        name=f"{DOC_ROOT}/users/alice",
        transaction=txn_token,
    )
    doc = await servicer.GetDocument(get_req, _FakeContext())
    assert doc.fields["name"].string_value == "Alice"

    # Verify read_set is populated
    txn_id = txn_token.decode("ascii")
    txn = await storage.get_transaction(PROJECT, DATABASE, txn_id)
    assert txn is not None
    assert "users/alice" in txn.read_set

    # Commit with no writes
    commit_req = firestore_pb2.CommitRequest(
        database=DB_ROOT,
        transaction=txn_token,
    )
    commit_resp = await servicer.Commit(commit_req, _FakeContext())
    assert commit_resp.HasField("commit_time")

    # Transaction should be cleaned up
    txn_after = await storage.get_transaction(PROJECT, DATABASE, txn_id)
    assert txn_after is None


# ---------------------------------------------------------------------------
# Test 3: Read doc in txn, mutate outside, commit → ABORTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_aborted_when_read_doc_mutated_outside_txn() -> None:
    servicer, _storage = _make_servicer()

    # Create a document
    await _create_doc(servicer, "items", "item1", value="old")

    # Begin transaction
    begin_resp = await servicer.BeginTransaction(
        firestore_pb2.BeginTransactionRequest(database=DB_ROOT), _FakeContext()
    )
    txn_token = begin_resp.transaction

    # Read inside txn
    await servicer.GetDocument(
        firestore_pb2.GetDocumentRequest(
            name=f"{DOC_ROOT}/items/item1",
            transaction=txn_token,
        ),
        _FakeContext(),
    )

    # Mutate the doc OUTSIDE the transaction (non-transactional update via BatchWrite)
    batch_req = firestore_pb2.BatchWriteRequest(
        database=DB_ROOT,
        writes=[_make_update_write(f"{DOC_ROOT}/items/item1", value="new")],
    )
    await servicer.BatchWrite(batch_req, _FakeContext())

    # Now commit the transaction with a write — should be ABORTED
    commit_req = firestore_pb2.CommitRequest(
        database=DB_ROOT,
        transaction=txn_token,
        writes=[_make_update_write(f"{DOC_ROOT}/items/item1", value="txn-value")],
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.Commit(commit_req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.ABORTED


# ---------------------------------------------------------------------------
# Test 4: Read-only transaction rejects writes on commit → INVALID_ARGUMENT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_transaction_rejects_writes_on_commit() -> None:
    servicer, _ = _make_servicer()
    await _create_doc(servicer, "docs", "d1", x="1")

    # Begin read-only transaction
    opts = common_pb2.TransactionOptions(read_only=common_pb2.TransactionOptions.ReadOnly())
    begin_resp = await servicer.BeginTransaction(
        firestore_pb2.BeginTransactionRequest(database=DB_ROOT, options=opts),
        _FakeContext(),
    )
    txn_token = begin_resp.transaction

    # Attempt commit with writes
    commit_req = firestore_pb2.CommitRequest(
        database=DB_ROOT,
        transaction=txn_token,
        writes=[_make_update_write(f"{DOC_ROOT}/docs/d1", x="2")],
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.Commit(commit_req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


# ---------------------------------------------------------------------------
# Test 5: Rollback drops txn; subsequent commit → INVALID_ARGUMENT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_drops_txn_subsequent_commit_fails() -> None:
    servicer, storage = _make_servicer()

    begin_resp = await servicer.BeginTransaction(
        firestore_pb2.BeginTransactionRequest(database=DB_ROOT), _FakeContext()
    )
    txn_token = begin_resp.transaction
    txn_id = txn_token.decode("ascii")

    # Rollback
    rollback_req = firestore_pb2.RollbackRequest(
        database=DB_ROOT,
        transaction=txn_token,
    )
    rollback_resp = await servicer.Rollback(rollback_req, _FakeContext())
    # Rollback returns Empty
    assert rollback_resp is not None

    # Verify txn is dropped
    txn = await storage.get_transaction(PROJECT, DATABASE, txn_id)
    assert txn is None

    # Try to commit with the same token — should fail
    commit_req = firestore_pb2.CommitRequest(
        database=DB_ROOT,
        transaction=txn_token,
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.Commit(commit_req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


# ---------------------------------------------------------------------------
# Test 6: TTL sweeper drops a stale transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ttl_sweeper_drops_stale_transaction() -> None:
    storage = InMemoryStorage()
    sweeper = TransactionTtlSweeper(storage, interval_s=0.05, ttl=timedelta(milliseconds=100))

    # Manually begin a transaction
    txn = await begin_transaction(storage, PROJECT, DATABASE, read_only=False)
    txn_id = txn.txn_id

    # Verify it exists
    assert await storage.get_transaction(PROJECT, DATABASE, txn_id) is not None

    # Start sweeper and wait enough time for ttl to expire and sweep to run
    await sweeper.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await sweeper.stop()

    # Transaction should have been swept
    result = await storage.get_transaction(PROJECT, DATABASE, txn_id)
    assert result is None


# ---------------------------------------------------------------------------
# Test 7: Read-only txn with read_time filters out docs created after that time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_txn_with_read_time_filters_newer_docs() -> None:
    servicer, _storage = _make_servicer()

    # Create a document and capture a timestamp before it
    read_time = datetime.now(tz=UTC)

    # Wait briefly and create doc AFTER the read_time
    await asyncio.sleep(0.01)
    await _create_doc(servicer, "users", "bob", name="Bob")

    # Convert read_time to a Timestamp proto
    read_ts = Timestamp()
    read_ts.FromDatetime(read_time)

    # Begin a read-only transaction with a read_time set before the doc was created
    opts = common_pb2.TransactionOptions(
        read_only=common_pb2.TransactionOptions.ReadOnly(read_time=read_ts)
    )
    begin_resp = await servicer.BeginTransaction(
        firestore_pb2.BeginTransactionRequest(database=DB_ROOT, options=opts),
        _FakeContext(),
    )
    txn_token = begin_resp.transaction

    # GetDocument inside txn should return NOT_FOUND (doc created after read_time)
    get_req = firestore_pb2.GetDocumentRequest(
        name=f"{DOC_ROOT}/users/bob",
        transaction=txn_token,
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetDocument(get_req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


# ---------------------------------------------------------------------------
# Test 8: Successfully committed txn drops the txn (subsequent rollback no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_commit_drops_txn_rollback_is_noop() -> None:
    servicer, storage = _make_servicer()

    await _create_doc(servicer, "things", "t1", v="1")

    begin_resp = await servicer.BeginTransaction(
        firestore_pb2.BeginTransactionRequest(database=DB_ROOT), _FakeContext()
    )
    txn_token = begin_resp.transaction
    txn_id = txn_token.decode("ascii")

    # Read inside txn
    await servicer.GetDocument(
        firestore_pb2.GetDocumentRequest(
            name=f"{DOC_ROOT}/things/t1",
            transaction=txn_token,
        ),
        _FakeContext(),
    )

    # Commit
    commit_req = firestore_pb2.CommitRequest(
        database=DB_ROOT,
        transaction=txn_token,
    )
    await servicer.Commit(commit_req, _FakeContext())

    # Txn dropped
    txn = await storage.get_transaction(PROJECT, DATABASE, txn_id)
    assert txn is None

    # Subsequent rollback with same token is a no-op (no error)
    rollback_req = firestore_pb2.RollbackRequest(
        database=DB_ROOT,
        transaction=txn_token,
    )
    ctx = _FakeContext()
    # rollback on unknown txn_id should not error (it's a no-op per spec)
    await servicer.Rollback(rollback_req, ctx)
    assert ctx.aborted is None
