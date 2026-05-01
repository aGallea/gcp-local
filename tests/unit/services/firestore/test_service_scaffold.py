import pytest

from gcp_local.core.context import Context
from gcp_local.services.firestore import FirestoreService


@pytest.mark.asyncio
async def test_service_starts_and_health_reports_running(tmp_path) -> None:
    svc = FirestoreService()
    ctx = Context(persist=False, data_dir=str(tmp_path), port_overrides={"firestore": 0})
    try:
        await svc.start(ctx)
        assert svc.health().ok is True
    finally:
        await svc.stop()
    assert svc.health().ok is False


def test_service_default_port_is_8080() -> None:
    svc = FirestoreService()
    ports = list(svc.default_ports)
    assert len(ports) == 1
    assert ports[0].number == 8080
    assert ports[0].protocol == "grpc"
