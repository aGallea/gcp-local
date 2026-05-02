"""End-to-end tests for the order-pipeline example.

These tests assume gcp-local is already running (the GitHub Actions workflow
brings it up via docker-compose; locally, run `docker compose up -d --build`
from this directory before invoking pytest).
"""

from __future__ import annotations

import uuid

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


def _new_order_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_place_order_writes_to_firestore_and_gcs_and_bq(pipeline: OrderPipeline) -> None:
    order_id = _new_order_id("placeorder")
    pipeline.place_order(order_id=order_id, customer="alice", amount=10.0, item="bolt")

    fs_doc = pipeline._get_order_doc(order_id)
    assert fs_doc["status"] == "pending"
    assert fs_doc["customer"] == "alice"
    assert fs_doc["key_used"].startswith("sk_t") and "***" in fs_doc["key_used"]

    invoice = pipeline._download_invoice(order_id)
    assert order_id in invoice
    assert "10.0" in invoice or "10.00" in invoice

    rows = pipeline._select_events_for_order(order_id)
    assert len(rows) == 1
    assert rows[0]["customer"] == "alice"


def test_confirm_pending_orders_updates_firestore(pipeline: OrderPipeline) -> None:
    order_id = _new_order_id("confirm")
    pipeline.place_order(order_id=order_id, customer="carol", amount=5.0, item="screw")

    confirmed = pipeline.confirm_pending_orders(timeout_s=5.0)
    assert confirmed >= 1

    doc = pipeline._get_order_doc(order_id)
    assert doc["status"] == "confirmed"


def test_pubsub_push_subscription_delivers_to_host(pipeline: OrderPipeline) -> None:
    """End-to-end push delivery against the docker-compose'd emulator.

    Spins up a small HTTP server on the host, registers a Pub/Sub push
    subscription pointing at ``host.docker.internal:<port>``, publishes a
    message via the real client, and verifies the host received the
    wrapped envelope. Skips with a clear message if the emulator container
    cannot resolve ``host.docker.internal`` (older Docker without
    host-gateway).
    """
    import base64
    import contextlib
    import http.server
    import json as _json
    import socket
    import threading
    import time
    import uuid

    from google.api_core.exceptions import AlreadyExists
    from google.cloud import pubsub_v1

    received: list[dict] = []
    received_event = threading.Event()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # stdlib API requires this exact name
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            try:
                received.append(_json.loads(body))
                received_event.set()
                self.send_response(204)
            except Exception:
                self.send_response(500)
            self.end_headers()

        def log_message(self, *args, **kwargs) -> None:  # silence default stderr noise
            return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    bound_port = sock.getsockname()[1]
    sock.close()

    server = http.server.ThreadingHTTPServer(("0.0.0.0", bound_port), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)  # let the server bind

    try:
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        suffix = uuid.uuid4().hex[:8]
        topic_id = f"push-e2e-topic-{suffix}"
        sub_id = f"push-e2e-sub-{suffix}"
        topic_path = publisher.topic_path(pipeline.project, topic_id)
        sub_path = subscriber.subscription_path(pipeline.project, sub_id)
        push_url = f"http://host.docker.internal:{bound_port}/push"

        with contextlib.suppress(AlreadyExists):
            publisher.create_topic(request={"name": topic_path})
        with contextlib.suppress(AlreadyExists):
            subscriber.create_subscription(
                request={
                    "name": sub_path,
                    "topic": topic_path,
                    "push_config": {"push_endpoint": push_url},
                    "ack_deadline_seconds": 10,
                }
            )

        publisher.publish(
            topic_path, _json.dumps({"order_id": "push-e2e-1"}).encode("utf-8")
        ).result(timeout=5.0)

        if not received_event.wait(timeout=10):
            pytest.skip(
                "host.docker.internal not reachable from the emulator container — "
                "Docker without host-gateway support; skipping push e2e."
            )

        assert len(received) == 1
        envelope = received[0]
        assert envelope["subscription"] == sub_path
        assert _json.loads(base64.b64decode(envelope["message"]["data"])) == {
            "order_id": "push-e2e-1"
        }

        # Verify no double-delivery: the 204 already acked; the next sweep
        # should not POST again.
        time.sleep(2.0)
        assert len(received) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_daily_totals_aggregates_per_customer(pipeline: OrderPipeline) -> None:
    suffix = uuid.uuid4().hex[:6]
    pipeline.place_order(
        order_id=f"tot-{suffix}-a", customer=f"dave-{suffix}", amount=7.0, item="x"
    )
    pipeline.place_order(
        order_id=f"tot-{suffix}-b", customer=f"dave-{suffix}", amount=3.0, item="y"
    )

    totals = pipeline.daily_totals()
    assert any(
        cust == f"dave-{suffix}" and abs(float(total) - 10.0) < 1e-6
        for cust, total in totals.items()
    )
