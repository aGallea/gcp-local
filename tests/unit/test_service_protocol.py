from typing import ClassVar

from gcp_local.core.service import HealthStatus, Port, Service


class GoodService:
    name = "good"
    default_ports: ClassVar[list[Port]] = [Port(1234, "rest")]

    async def start(self, ctx):
        return None

    async def stop(self):
        return None

    async def reset_state(self):
        return None

    def health(self):
        return HealthStatus(ok=True)


def test_port_is_frozen():
    p = Port(1234, "rest")
    assert p.number == 1234
    assert p.protocol == "rest"


def test_health_status_defaults():
    hs = HealthStatus(ok=True)
    assert hs.ok is True
    assert hs.message == ""


def test_service_protocol_structural():
    svc = GoodService()
    assert isinstance(svc, Service)
