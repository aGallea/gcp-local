"""Unit tests for Firestore Commit + BatchWrite RPCs (Task 8)."""

from __future__ import annotations

import grpc
import pytest
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.generated.google.firestore.v1 import (
    common_pb2,
    document_pb2,
    firestore_pb2,
    write_pb2,
)
from gcp_local.services.firestore.servicer import FirestoreServicer
from gcp_local.services.firestore.storage import InMemoryStorage

# ---------------------------------------------------------------------------
# Fake gRPC context
# ---------------------------------------------------------------------------


class _Aborted(Exception):
    pass


class _FakeContext:
    """Minimal stand-in for grpc.aio.ServicerContext."""

    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise _Aborted()

    def HasField(self, name: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Stub StateHub that records published events
# ---------------------------------------------------------------------------


class _StateHubStub:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> None:
        self.events.append((topic, payload))


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------

PROJECT = "my-project"
DATABASE = "(default)"
DB_ROOT = f"projects/{PROJECT}/databases/{DATABASE}"
DOC_ROOT = f"{DB_ROOT}/documents"


def _make_servicer(
    hub: _StateHubStub | None = None,
) -> tuple[FirestoreServicer, InMemoryStorage, _StateHubStub]:
    hub = hub or _StateHubStub()
    storage = InMemoryStorage()
    servicer = FirestoreServicer(storage=storage, state_hub=hub)  # type: ignore[arg-type]
    return servicer, storage, hub


def _str_val(s: str) -> document_pb2.Value:
    return document_pb2.Value(string_value=s)


def _int_val(n: int) -> document_pb2.Value:
    return document_pb2.Value(integer_value=n)


def _doc(path: str, **fields: str) -> document_pb2.Document:
    return document_pb2.Document(
        name=f"{DOC_ROOT}/{path}",
        fields={k: _str_val(v) for k, v in fields.items()},
    )


def _update_write(path: str, **fields: str) -> write_pb2.Write:
    return write_pb2.Write(update=_doc(path, **fields))


def _delete_write(path: str) -> write_pb2.Write:
    return write_pb2.Write(delete=f"{DOC_ROOT}/{path}")


def _masked_write(path: str, mask_fields: list[str], **fields: str) -> write_pb2.Write:
    return write_pb2.Write(
        update=_doc(path, **fields),
        update_mask=common_pb2.DocumentMask(field_paths=mask_fields),
    )


def _precondition_exists(exists: bool) -> common_pb2.Precondition:
    return common_pb2.Precondition(exists=exists)


async def _commit(
    servicer: FirestoreServicer,
    writes: list[write_pb2.Write],
    *,
    transaction: bytes = b"",
) -> firestore_pb2.CommitResponse:
    req = firestore_pb2.CommitRequest(
        database=DB_ROOT,
        writes=writes,
        transaction=transaction,
    )
    return await servicer.Commit(req, _FakeContext())


async def _batch_write(
    servicer: FirestoreServicer,
    writes: list[write_pb2.Write],
) -> firestore_pb2.BatchWriteResponse:
    req = firestore_pb2.BatchWriteRequest(
        database=DB_ROOT,
        writes=writes,
    )
    return await servicer.BatchWrite(req, _FakeContext())


# ---------------------------------------------------------------------------
# Test 1: Single update write — commit_time + WriteResult + doc persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_single_update_returns_write_result() -> None:
    servicer, storage, _ = _make_servicer()
    resp = await _commit(servicer, [_update_write("users/alice", name="Alice")])

    assert len(resp.write_results) == 1
    wr = resp.write_results[0]
    # commit_time must be set on the response
    assert resp.commit_time.seconds > 0
    # WriteResult.update_time must equal commit_time
    assert wr.update_time == resp.commit_time

    # Doc is persisted
    rec = await storage.get_document(PROJECT, DATABASE, "users/alice")
    assert rec.fields["name"] == "Alice"


# ---------------------------------------------------------------------------
# Test 2: Multi-write Commit — all docs land
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_multi_write_all_persist() -> None:
    servicer, storage, _ = _make_servicer()
    writes = [
        _update_write("users/alice", name="Alice"),
        _update_write("users/bob", name="Bob"),
        _update_write("users/carol", name="Carol"),
    ]
    resp = await _commit(servicer, writes)

    assert len(resp.write_results) == 3
    for path in ("users/alice", "users/bob", "users/carol"):
        rec = await storage.get_document(PROJECT, DATABASE, path)
        assert rec is not None


# ---------------------------------------------------------------------------
# Test 3: update_mask merges only masked fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_update_mask_merges_only_masked_fields() -> None:
    servicer, storage, _ = _make_servicer()
    # Seed the doc with two fields
    await _commit(servicer, [_update_write("items/one", color="red", size="large")])

    # Commit with mask covering only "color"
    masked = _masked_write("items/one", ["color"], color="blue", size="ignored-by-mask")
    await _commit(servicer, [masked])

    rec = await storage.get_document(PROJECT, DATABASE, "items/one")
    assert rec.fields["color"] == "blue"
    # "size" must be unchanged — mask didn't include it
    assert rec.fields["size"] == "large"


# ---------------------------------------------------------------------------
# Test 4: update_transforms SERVER_TIMESTAMP + Increment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_update_transforms_populate_transform_results() -> None:
    servicer, storage, _ = _make_servicer()

    ts_transform = write_pb2.DocumentTransform.FieldTransform(
        field_path="ts",
        set_to_server_value=write_pb2.DocumentTransform.FieldTransform.REQUEST_TIME,
    )
    inc_transform = write_pb2.DocumentTransform.FieldTransform(
        field_path="counter",
        increment=_int_val(5),
    )
    w = write_pb2.Write(
        update=_doc("counters/c1", note="init"),
        update_transforms=[ts_transform, inc_transform],
    )
    resp = await _commit(servicer, [w])

    wr = resp.write_results[0]
    # Two transform results in order: ts, then counter (0 + 5 = 5)
    assert len(wr.transform_results) == 2
    # counter result = 5 (integer)
    assert wr.transform_results[1].integer_value == 5

    # Check persisted
    rec = await storage.get_document(PROJECT, DATABASE, "counters/c1")
    assert rec.fields["counter"] == 5


# ---------------------------------------------------------------------------
# Test 5: delete write removes doc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_delete_removes_document() -> None:
    servicer, storage, _ = _make_servicer()
    await _commit(servicer, [_update_write("things/x", val="v")])

    resp = await _commit(servicer, [_delete_write("things/x")])

    assert len(resp.write_results) == 1
    # delete WriteResult has no update_time (zero Timestamp)
    assert resp.write_results[0].update_time.seconds == 0

    # Doc is gone
    from gcp_local.services.firestore.errors import DocumentNotFound

    with pytest.raises(DocumentNotFound):
        await storage.get_document(PROJECT, DATABASE, "things/x")


# ---------------------------------------------------------------------------
# Test 6: Precondition exists=true on missing doc → FAILED_PRECONDITION, no writes applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_precondition_exists_on_missing_fails_atomically() -> None:
    servicer, storage, _ = _make_servicer()

    w = write_pb2.Write(
        update=_doc("docs/a", val="new"),
        current_document=_precondition_exists(True),
    )
    ctx = _FakeContext()
    req = firestore_pb2.CommitRequest(database=DB_ROOT, writes=[w])
    with pytest.raises(_Aborted):
        await servicer.Commit(req, ctx)

    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION

    # Nothing was written
    from gcp_local.services.firestore.errors import DocumentNotFound

    with pytest.raises(DocumentNotFound):
        await storage.get_document(PROJECT, DATABASE, "docs/a")


# ---------------------------------------------------------------------------
# Test 7: Precondition update_time mismatch → FAILED_PRECONDITION, nothing applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_precondition_update_time_mismatch_fails_atomically() -> None:
    servicer, storage, _ = _make_servicer()
    # Seed the doc
    await _commit(servicer, [_update_write("docs/b", val="original")])

    # Provide a wrong update_time in the precondition
    wrong_ts = Timestamp(seconds=1, nanos=0)
    w = write_pb2.Write(
        update=_doc("docs/b", val="updated"),
        current_document=common_pb2.Precondition(update_time=wrong_ts),
    )
    ctx = _FakeContext()
    req = firestore_pb2.CommitRequest(database=DB_ROOT, writes=[w])
    with pytest.raises(_Aborted):
        await servicer.Commit(req, ctx)

    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION

    # Original value unchanged
    rec = await storage.get_document(PROJECT, DATABASE, "docs/b")
    assert rec.fields["val"] == "original"


# ---------------------------------------------------------------------------
# Test 8: StateHub receives firestore.document.written for every successful write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_emits_state_hub_events_per_write() -> None:
    servicer, _, hub = _make_servicer()

    writes = [
        _update_write("users/alice", name="Alice"),
        _update_write("users/bob", name="Bob"),
        _delete_write("users/alice"),  # won't exist yet, but delete is idempotent
    ]
    await _commit(servicer, writes)

    assert len(hub.events) == 3
    for topic, payload in hub.events:
        assert topic == "firestore.document.written"
        assert payload["project"] == PROJECT
        assert payload["database"] == DATABASE
        assert "path" in payload
        assert "operation" in payload
        assert "update_time" in payload

    # operation labels
    ops = [payload["operation"] for _, payload in hub.events]
    assert ops[0] in ("create", "update")
    assert ops[1] in ("create", "update")
    assert ops[2] == "delete"


# ---------------------------------------------------------------------------
# Test 9: BatchWrite happy path — all OK statuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_write_happy_path_all_ok() -> None:
    servicer, storage, _ = _make_servicer()
    writes = [
        _update_write("batch/doc1", val="a"),
        _update_write("batch/doc2", val="b"),
    ]
    resp = await _batch_write(servicer, writes)

    assert len(resp.write_results) == 2
    assert len(resp.status) == 2
    for s in resp.status:
        assert s.code == 0  # google.rpc.Code.OK

    await storage.get_document(PROJECT, DATABASE, "batch/doc1")
    await storage.get_document(PROJECT, DATABASE, "batch/doc2")


# ---------------------------------------------------------------------------
# Test 10: BatchWrite mixed — one fails, others succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_write_mixed_failure_partial_success() -> None:
    servicer, storage, _ = _make_servicer()

    # Write 0: OK (no precondition)
    w_ok = _update_write("mixed/docA", val="a")
    # Write 1: will fail (exists=true on a missing doc)
    w_fail = write_pb2.Write(
        update=_doc("mixed/docB", val="b"),
        current_document=_precondition_exists(True),
    )
    # Write 2: also OK
    w_ok2 = _update_write("mixed/docC", val="c")

    resp = await _batch_write(servicer, [w_ok, w_fail, w_ok2])

    assert len(resp.status) == 3
    assert resp.status[0].code == 0  # OK
    assert resp.status[1].code != 0  # error
    assert resp.status[2].code == 0  # OK

    # Successful writes ARE persisted
    await storage.get_document(PROJECT, DATABASE, "mixed/docA")
    await storage.get_document(PROJECT, DATABASE, "mixed/docC")

    # Failed write is NOT persisted
    from gcp_local.services.firestore.errors import DocumentNotFound

    with pytest.raises(DocumentNotFound):
        await storage.get_document(PROJECT, DATABASE, "mixed/docB")


# ---------------------------------------------------------------------------
# Test 11: Commit with non-empty transaction → UNIMPLEMENTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_with_unknown_transaction_returns_invalid_argument() -> None:
    """Transactional Commit is now implemented (Task 12).

    An unknown (or expired) transaction token results in INVALID_ARGUMENT,
    not UNIMPLEMENTED.
    """
    servicer, _, _ = _make_servicer()
    ctx = _FakeContext()
    req = firestore_pb2.CommitRequest(
        database=DB_ROOT,
        writes=[_update_write("docs/x", val="v")],
        transaction=b"deadbeefdeadbeef",  # valid ASCII but unknown txn_id
    )
    with pytest.raises(_Aborted):
        await servicer.Commit(req, ctx)

    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT
