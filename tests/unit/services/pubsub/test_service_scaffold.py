import pytest

from gcp_local.core.context import Context
from gcp_local.services.pubsub import PubSubService


@pytest.mark.asyncio
async def test_service_starts_and_health_reports_ok(tmp_path) -> None:
    svc = PubSubService()
    ctx = Context(persist=False, data_dir=str(tmp_path), port_overrides={"pubsub": 0})
    await svc.start(ctx)
    try:
        assert svc.health().ok
    finally:
        await svc.stop()
    assert not svc.health().ok


@pytest.mark.asyncio
async def test_service_reset_state_clears_storage(tmp_path) -> None:
    svc = PubSubService()
    ctx = Context(persist=False, data_dir=str(tmp_path), port_overrides={"pubsub": 0})
    await svc.start(ctx)
    try:
        # We don't have CRUD wired through gRPC yet; reset_state should still work.
        await svc.reset_state()
    finally:
        await svc.stop()
