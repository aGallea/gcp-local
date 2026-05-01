"""End-to-end Firestore tests against the in-process emulator using google-cloud-firestore.

The `emulator` fixture boots gcp-local in-process as an asyncio task. The Firestore
client is synchronous/blocking, so all calls are dispatched via ``asyncio.to_thread``
to avoid starving the loop and the emulator gRPC server.

FIRESTORE_EMULATOR_HOST is set by the ``_set_emulator_host`` fixture before any
``firestore.Client()`` is constructed.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google.api_core import exceptions as gax_exc
from google.cloud import firestore

# ---------------------------------------------------------------------------
# Env-var fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_emulator_host(emulator_endpoints):
    """Set FIRESTORE_EMULATOR_HOST so that firestore.Client() connects to the emulator."""
    host = emulator_endpoints["firestore"]
    os.environ["FIRESTORE_EMULATOR_HOST"] = host
    yield
    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db(database: str = "(default)") -> firestore.Client:
    return firestore.Client(project="test-project", database=database)


# ---------------------------------------------------------------------------
# 1. Set / Get / Update / Delete with subcollection
# ---------------------------------------------------------------------------


async def test_set_get_round_trip() -> None:
    db = _db()
    await asyncio.to_thread(
        db.collection("users").document("alice").set, {"name": "Alice", "score": 0}
    )
    snap = await asyncio.to_thread(db.collection("users").document("alice").get)
    assert snap.exists
    assert snap.to_dict() == {"name": "Alice", "score": 0}


async def test_subcollection_set_get() -> None:
    db = _db()
    await asyncio.to_thread(
        db.collection("users").document("alice").set, {"name": "Alice", "score": 0}
    )
    post_ref = db.collection("users").document("alice").collection("posts").document("p1")
    await asyncio.to_thread(post_ref.set, {"title": "Hello World"})

    snap = await asyncio.to_thread(post_ref.get)
    assert snap.exists
    assert snap.to_dict() == {"title": "Hello World"}


async def test_update_partial() -> None:
    db = _db()
    ref = db.collection("users").document("bob")
    await asyncio.to_thread(ref.set, {"name": "Bob", "score": 10, "extra": "keep"})
    await asyncio.to_thread(ref.update, {"score": 20})
    snap = await asyncio.to_thread(ref.get)
    data = snap.to_dict()
    assert data["score"] == 20
    assert data["name"] == "Bob"
    assert data["extra"] == "keep"


async def test_delete_document() -> None:
    db = _db()
    ref = db.collection("users").document("charlie")
    await asyncio.to_thread(ref.set, {"name": "Charlie"})
    snap = await asyncio.to_thread(ref.get)
    assert snap.exists

    await asyncio.to_thread(ref.delete)
    snap = await asyncio.to_thread(ref.get)
    assert not snap.exists


async def test_set_get_update_delete_subcollection() -> None:
    db = _db()
    user_ref = db.collection("users").document("dave")
    await asyncio.to_thread(user_ref.set, {"name": "Dave", "score": 5})

    post_ref = user_ref.collection("posts").document("p1")
    await asyncio.to_thread(post_ref.set, {"title": "First Post"})

    # Update parent
    await asyncio.to_thread(user_ref.update, {"score": 99})
    snap = await asyncio.to_thread(user_ref.get)
    assert snap.to_dict()["score"] == 99

    # Delete subcollection doc
    await asyncio.to_thread(post_ref.delete)
    snap = await asyncio.to_thread(post_ref.get)
    assert not snap.exists


# ---------------------------------------------------------------------------
# 2. Where + order_by + limit
# ---------------------------------------------------------------------------


async def test_where_order_limit() -> None:
    db = _db()
    coll = db.collection("scores")
    docs: list[dict[str, Any]] = [
        {"name": f"user{i}", "score": i * 2}
        for i in range(5)  # scores: 0, 2, 4, 6, 8
    ]
    for d in docs:
        await asyncio.to_thread(coll.add, d)

    query = (
        coll.where(filter=firestore.FieldFilter("score", ">", 4))
        .order_by("score", direction=firestore.Query.DESCENDING)
        .limit(2)
    )
    results = await asyncio.to_thread(query.get)
    scores = [r.to_dict()["score"] for r in results]
    assert scores == [8, 6]


# ---------------------------------------------------------------------------
# 3. Composite filter (And / Or)
# ---------------------------------------------------------------------------


async def test_composite_and_filter() -> None:
    db = _db()
    coll = db.collection("items")
    await asyncio.to_thread(coll.document("a").set, {"type": "fruit", "price": 1})
    await asyncio.to_thread(coll.document("b").set, {"type": "fruit", "price": 5})
    await asyncio.to_thread(coll.document("c").set, {"type": "veggie", "price": 2})

    query = coll.where(
        filter=firestore.And(
            filters=[
                firestore.FieldFilter("type", "==", "fruit"),
                firestore.FieldFilter("price", ">", 2),
            ]
        )
    )
    results = await asyncio.to_thread(query.get)
    assert len(results) == 1
    assert results[0].to_dict()["price"] == 5


async def test_composite_or_filter() -> None:
    db = _db()
    coll = db.collection("mixed")
    await asyncio.to_thread(coll.document("x").set, {"cat": "A", "val": 10})
    await asyncio.to_thread(coll.document("y").set, {"cat": "B", "val": 20})
    await asyncio.to_thread(coll.document("z").set, {"cat": "C", "val": 30})

    query = coll.where(
        filter=firestore.Or(
            filters=[
                firestore.FieldFilter("cat", "==", "A"),
                firestore.FieldFilter("cat", "==", "C"),
            ]
        )
    )
    results = await asyncio.to_thread(query.get)
    cats = sorted(r.to_dict()["cat"] for r in results)
    assert cats == ["A", "C"]


# ---------------------------------------------------------------------------
# 4. count() aggregation
# ---------------------------------------------------------------------------


async def test_count_aggregation_total() -> None:
    db = _db()
    coll = db.collection("counters")
    for i in range(7):
        await asyncio.to_thread(coll.document(f"d{i}").set, {"n": i})

    result = await asyncio.to_thread(coll.count().get)
    count_val = result[0][0].value
    assert count_val == 7


async def test_count_aggregation_with_filter() -> None:
    db = _db()
    coll = db.collection("filtered_counts")
    for i in range(6):
        await asyncio.to_thread(coll.document(f"d{i}").set, {"active": i % 2 == 0})

    query = coll.where(filter=firestore.FieldFilter("active", "==", True))
    result = await asyncio.to_thread(query.count().get)
    count_val = result[0][0].value
    assert count_val == 3


# ---------------------------------------------------------------------------
# 5. Collection-group query
# ---------------------------------------------------------------------------


async def test_collection_group_query() -> None:
    db = _db()
    await asyncio.to_thread(
        db.collection("users").document("a").collection("items").document("i1").set,
        {"label": "item-a"},
    )
    await asyncio.to_thread(
        db.collection("users").document("b").collection("items").document("i2").set,
        {"label": "item-b"},
    )

    results = await asyncio.to_thread(db.collection_group("items").get)
    labels = sorted(r.to_dict()["label"] for r in results)
    assert labels == ["item-a", "item-b"]


# ---------------------------------------------------------------------------
# 6. Transaction happy path
# ---------------------------------------------------------------------------


async def test_transaction_happy_path() -> None:
    db = _db()
    ref = db.collection("accounts").document("acct1")
    await asyncio.to_thread(ref.set, {"balance": 100})

    @firestore.transactional
    def _transfer(txn: firestore.Transaction, doc_ref: Any) -> None:
        snap = doc_ref.get(transaction=txn)
        new_balance = snap.get("balance") + 50
        txn.update(doc_ref, {"balance": new_balance})

    txn = db.transaction()
    await asyncio.to_thread(_transfer, txn, ref)

    snap = await asyncio.to_thread(ref.get)
    assert snap.to_dict()["balance"] == 150


# ---------------------------------------------------------------------------
# 7. Transaction conflict → Aborted
# ---------------------------------------------------------------------------


async def test_transaction_conflict_raises_aborted() -> None:
    db = _db()
    ref = db.collection("conflict_docs").document("shared")
    await asyncio.to_thread(ref.set, {"v": 1})

    # Open a manual transaction with max_attempts=1 so the client does NOT retry.
    txn = db.transaction(max_attempts=1)

    def _conflict_scenario() -> None:
        # Begin the transaction and read the doc (registers it in read_set).
        txn._begin()
        ref.get(transaction=txn)

        # A second client mutates the doc outside the transaction (conflict!).
        db2 = _db()
        db2.collection("conflict_docs").document("shared").set({"v": 2})

        # Now commit — the read_set check should detect the conflict.
        txn._commit()

    with pytest.raises(gax_exc.Aborted):
        await asyncio.to_thread(_conflict_scenario)


# ---------------------------------------------------------------------------
# 8. Increment round-trip
# ---------------------------------------------------------------------------


async def test_increment_round_trip() -> None:
    db = _db()
    ref = db.collection("scores2").document("player1")
    await asyncio.to_thread(ref.set, {"score": 0})
    await asyncio.to_thread(ref.update, {"score": firestore.Increment(5)})
    snap = await asyncio.to_thread(ref.get)
    assert snap.to_dict()["score"] == 5


# ---------------------------------------------------------------------------
# 9. SERVER_TIMESTAMP round-trip
# ---------------------------------------------------------------------------


async def test_server_timestamp_round_trip() -> None:
    db = _db()
    ref = db.collection("events").document("e1")
    before = datetime.now(tz=UTC)
    await asyncio.to_thread(ref.set, {"created": firestore.SERVER_TIMESTAMP})
    snap = await asyncio.to_thread(ref.get)
    data = snap.to_dict()
    assert "created" in data
    ts = data["created"]
    # Should be a datetime-like object close to now
    if hasattr(ts, "replace"):
        ts_aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
    else:
        ts_aware = ts
    assert ts_aware >= before - timedelta(seconds=5)
    assert ts_aware <= datetime.now(tz=UTC) + timedelta(seconds=5)


# ---------------------------------------------------------------------------
# 10. Multi-database isolation
# ---------------------------------------------------------------------------


async def test_multi_database_isolation() -> None:
    db_default = _db("(default)")
    db_staging = _db("staging")

    ref_default = db_default.collection("isolation").document("doc1")
    ref_staging = db_staging.collection("isolation").document("doc1")

    await asyncio.to_thread(ref_default.set, {"src": "default"})
    await asyncio.to_thread(ref_staging.set, {"src": "staging"})

    snap_default = await asyncio.to_thread(ref_default.get)
    snap_staging = await asyncio.to_thread(ref_staging.get)

    assert snap_default.to_dict()["src"] == "default"
    assert snap_staging.to_dict()["src"] == "staging"


# ---------------------------------------------------------------------------
# 11. Missing document returns exists=False (not an exception)
# ---------------------------------------------------------------------------


async def test_missing_document_returns_not_exists() -> None:
    db = _db()
    snap = await asyncio.to_thread(db.collection("nonexistent").document("ghost").get)
    assert not snap.exists


# ---------------------------------------------------------------------------
# 12. Duplicate create (AlreadyExists)
# ---------------------------------------------------------------------------


async def test_duplicate_create_raises_already_exists() -> None:
    db = _db()
    ref = db.collection("unique_docs").document("only-one")
    await asyncio.to_thread(ref.set, {"x": 1})

    with pytest.raises(gax_exc.AlreadyExists):
        # create() (not set()) fails if the document already exists.
        await asyncio.to_thread(ref.create, {"x": 2})
