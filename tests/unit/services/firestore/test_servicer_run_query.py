"""Unit tests for RunQuery and RunAggregationQuery RPCs (Task 11)."""

from __future__ import annotations

import grpc
import pytest
from google.protobuf.wrappers_pb2 import Int64Value

from gcp_local.generated.google.firestore.v1 import (
    document_pb2,
    firestore_pb2,
    query_pb2,
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
# Constants + helpers
# ---------------------------------------------------------------------------

PROJECT = "my-project"
DATABASE = "(default)"
DB_ROOT = f"projects/{PROJECT}/databases/{DATABASE}"
DOC_ROOT = f"{DB_ROOT}/documents"


def _make_servicer() -> tuple[FirestoreServicer, InMemoryStorage]:
    storage = InMemoryStorage()
    servicer = FirestoreServicer(storage=storage, state_hub=None)
    return servicer, storage


def _str_val(s: str) -> document_pb2.Value:
    return document_pb2.Value(string_value=s)


def _int_val(n: int) -> document_pb2.Value:
    return document_pb2.Value(integer_value=n)


async def _create(
    servicer: FirestoreServicer,
    collection: str,
    doc_id: str,
    **fields: document_pb2.Value,
) -> document_pb2.Document:
    req = firestore_pb2.CreateDocumentRequest(
        parent=DOC_ROOT,
        collection_id=collection,
        document_id=doc_id,
        document=document_pb2.Document(fields=fields),
    )
    return await servicer.CreateDocument(req, _FakeContext())


async def _collect_run_query(
    servicer: FirestoreServicer, request: firestore_pb2.RunQueryRequest
) -> list[firestore_pb2.RunQueryResponse]:
    ctx = _FakeContext()
    responses = []
    async for resp in servicer.RunQuery(request, ctx):
        responses.append(resp)
    return responses


async def _collect_run_agg_query(
    servicer: FirestoreServicer,
    request: firestore_pb2.RunAggregationQueryRequest,
) -> list[firestore_pb2.RunAggregationQueryResponse]:
    ctx = _FakeContext()
    responses = []
    async for resp in servicer.RunAggregationQuery(request, ctx):
        responses.append(resp)
    return responses


# ---------------------------------------------------------------------------
# RunQuery tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_query_returns_all_documents() -> None:
    """Seed 3 docs and expect all 3 returned plus a terminal read_time response."""
    servicer, _ = _make_servicer()
    for i in range(3):
        await _create(servicer, "users", f"doc{i}", name=_str_val(f"user{i}"))

    sq = query_pb2.StructuredQuery()
    (getattr(sq, "from", None) or sq.from_).extend(
        [query_pb2.StructuredQuery.CollectionSelector(collection_id="users")]
    )
    req = firestore_pb2.RunQueryRequest(parent=DOC_ROOT, structured_query=sq)
    responses = await _collect_run_query(servicer, req)

    # Last response is the terminal read_time-only response
    docs = [r for r in responses if r.HasField("document")]
    assert len(docs) == 3
    # Terminal response has no document
    terminal = responses[-1]
    assert not terminal.HasField("document")
    assert terminal.read_time.seconds > 0


@pytest.mark.asyncio
async def test_run_query_with_where_filter_returns_matching_docs() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "items", "a", status=_str_val("active"))
    await _create(servicer, "items", "b", status=_str_val("inactive"))
    await _create(servicer, "items", "c", status=_str_val("active"))

    field_filter = query_pb2.StructuredQuery.FieldFilter(
        field=query_pb2.StructuredQuery.FieldReference(field_path="status"),
        op=query_pb2.StructuredQuery.FieldFilter.Operator.EQUAL,
        value=document_pb2.Value(string_value="active"),
    )
    where = query_pb2.StructuredQuery.Filter(field_filter=field_filter)
    sq = query_pb2.StructuredQuery(where=where)
    (getattr(sq, "from", None) or sq.from_).extend(
        [query_pb2.StructuredQuery.CollectionSelector(collection_id="items")]
    )
    req = firestore_pb2.RunQueryRequest(parent=DOC_ROOT, structured_query=sq)
    responses = await _collect_run_query(servicer, req)

    docs = [r for r in responses if r.HasField("document")]
    assert len(docs) == 2
    paths = {r.document.name.split("/")[-1] for r in docs}
    assert paths == {"a", "c"}


@pytest.mark.asyncio
async def test_run_query_on_empty_collection_returns_only_read_time() -> None:
    servicer, _ = _make_servicer()
    sq = query_pb2.StructuredQuery()
    (getattr(sq, "from", None) or sq.from_).extend(
        [query_pb2.StructuredQuery.CollectionSelector(collection_id="empty")]
    )
    req = firestore_pb2.RunQueryRequest(parent=DOC_ROOT, structured_query=sq)
    responses = await _collect_run_query(servicer, req)

    assert len(responses) == 1
    assert not responses[0].HasField("document")
    assert responses[0].read_time.seconds > 0


# ---------------------------------------------------------------------------
# RunAggregationQuery tests
# ---------------------------------------------------------------------------


def _count_agg(
    alias: str = "n", up_to: int | None = None
) -> query_pb2.StructuredAggregationQuery.Aggregation:
    cnt = query_pb2.StructuredAggregationQuery.Aggregation.Count()
    if up_to is not None:
        cnt.up_to.CopyFrom(Int64Value(value=up_to))
    return query_pb2.StructuredAggregationQuery.Aggregation(count=cnt, alias=alias)


def _sum_agg(field_path: str, alias: str = "s") -> query_pb2.StructuredAggregationQuery.Aggregation:
    f = query_pb2.StructuredQuery.FieldReference(field_path=field_path)
    s = query_pb2.StructuredAggregationQuery.Aggregation.Sum(field=f)
    return query_pb2.StructuredAggregationQuery.Aggregation(sum=s, alias=alias)


@pytest.mark.asyncio
async def test_run_aggregation_query_count_all_docs() -> None:
    servicer, _ = _make_servicer()
    for i in range(5):
        await _create(servicer, "items", f"doc{i}", x=_int_val(i))

    sq = query_pb2.StructuredQuery()
    (getattr(sq, "from", None) or sq.from_).extend(
        [query_pb2.StructuredQuery.CollectionSelector(collection_id="items")]
    )
    saq = query_pb2.StructuredAggregationQuery(
        structured_query=sq,
        aggregations=[_count_agg("total")],
    )
    req = firestore_pb2.RunAggregationQueryRequest(
        parent=DOC_ROOT, structured_aggregation_query=saq
    )
    responses = await _collect_run_agg_query(servicer, req)

    assert len(responses) == 1
    result = responses[0].result
    assert result.aggregate_fields["total"].integer_value == 5


@pytest.mark.asyncio
async def test_run_aggregation_query_count_with_where_filter() -> None:
    servicer, _ = _make_servicer()
    await _create(servicer, "items", "a", active=document_pb2.Value(boolean_value=True))
    await _create(servicer, "items", "b", active=document_pb2.Value(boolean_value=False))
    await _create(servicer, "items", "c", active=document_pb2.Value(boolean_value=True))

    field_filter = query_pb2.StructuredQuery.FieldFilter(
        field=query_pb2.StructuredQuery.FieldReference(field_path="active"),
        op=query_pb2.StructuredQuery.FieldFilter.Operator.EQUAL,
        value=document_pb2.Value(boolean_value=True),
    )
    where = query_pb2.StructuredQuery.Filter(field_filter=field_filter)
    sq = query_pb2.StructuredQuery(where=where)
    (getattr(sq, "from", None) or sq.from_).extend(
        [query_pb2.StructuredQuery.CollectionSelector(collection_id="items")]
    )
    saq = query_pb2.StructuredAggregationQuery(
        structured_query=sq,
        aggregations=[_count_agg("n")],
    )
    req = firestore_pb2.RunAggregationQueryRequest(
        parent=DOC_ROOT, structured_aggregation_query=saq
    )
    responses = await _collect_run_agg_query(servicer, req)

    assert len(responses) == 1
    assert responses[0].result.aggregate_fields["n"].integer_value == 2


@pytest.mark.asyncio
async def test_run_aggregation_query_sum_field() -> None:
    servicer, _ = _make_servicer()
    for score in [10, 20, 30]:
        await _create(servicer, "scores", f"doc_{score}", score=_int_val(score))

    sq = query_pb2.StructuredQuery()
    (getattr(sq, "from", None) or sq.from_).extend(
        [query_pb2.StructuredQuery.CollectionSelector(collection_id="scores")]
    )
    saq = query_pb2.StructuredAggregationQuery(
        structured_query=sq,
        aggregations=[_sum_agg("score", alias="total")],
    )
    req = firestore_pb2.RunAggregationQueryRequest(
        parent=DOC_ROOT, structured_aggregation_query=saq
    )
    responses = await _collect_run_agg_query(servicer, req)

    assert len(responses) == 1
    assert responses[0].result.aggregate_fields["total"].integer_value == 60
    # read_time is populated
    assert responses[0].read_time.seconds > 0
