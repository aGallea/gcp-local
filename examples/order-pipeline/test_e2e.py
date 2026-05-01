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
