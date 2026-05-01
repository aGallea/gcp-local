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
