"""End-to-end tests for the order-pipeline example.

These tests assume gcp-local is already running (the GitHub Actions workflow
brings it up via docker-compose; locally, run `docker compose up -d --build`
from this directory before invoking pytest).
"""

from __future__ import annotations

import pytest
from order_pipeline import OrderPipeline


@pytest.fixture(scope="module")
def pipeline() -> OrderPipeline:
    """One pipeline instance shared across the module.

    Construction blocks until /_emulator/health reports ok; this also serves
    as the wait-for-ready gate for every other test in the file.
    """
    p = OrderPipeline()
    p.setup()
    return p


def test_pipeline_construction_blocks_until_emulator_ready(pipeline: OrderPipeline) -> None:
    # If we got here, __init__ saw ok=True within wait_timeout_s.
    # Sanity-check that the admin endpoint is still healthy after setup.
    assert pipeline.is_healthy()


def test_secret_seeded(pipeline: OrderPipeline) -> None:
    # setup() in the fixture should have seeded payment-api-key.
    assert pipeline._lookup_payment_key().startswith("sk_test_")


def test_gcs_invoice_upload(pipeline: OrderPipeline) -> None:
    pipeline._upload_invoice(
        order_id="test-order-001",
        body="Invoice for test-order-001\nAmount: 99.99",
    )
    body = pipeline._download_invoice("test-order-001")
    assert "Amount: 99.99" in body


def test_bigquery_insert_and_select(pipeline: OrderPipeline) -> None:
    import datetime
    import uuid

    order_id = f"bq-test-{uuid.uuid4().hex[:8]}"
    pipeline._insert_event(
        order_id=order_id,
        customer="alice",
        amount=42.5,
        item="widget",
        ts=datetime.datetime(2026, 5, 2, 12, 0, 0, tzinfo=datetime.UTC),
    )
    rows = pipeline._select_events_for_order(order_id)
    assert len(rows) == 1
    assert rows[0]["customer"] == "alice"
    assert float(rows[0]["amount"]) == 42.5


def test_pubsub_publish_and_pull(pipeline: OrderPipeline) -> None:
    pipeline._publish_order_event({"order_id": "ps-test-1", "status": "pending"})
    pulled = pipeline._pull_pending_events(timeout_s=2.0)
    assert any(msg.get("order_id") == "ps-test-1" for msg in pulled)


def test_firestore_write_and_read(pipeline: OrderPipeline) -> None:
    pipeline._write_order_doc(
        order_id="fs-test-1",
        customer="bob",
        amount=12.5,
        item="bolt",
        masked_key="sk_t***",
    )
    doc = pipeline._get_order_doc("fs-test-1")
    assert doc["status"] == "pending"
    assert doc["customer"] == "bob"
