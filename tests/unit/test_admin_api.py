from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.service import HealthStatus, Port


class TinyService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.default_ports = [Port(9999, "rest")]
        self.resets = 0

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self):
        self.resets += 1

    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, message=f"{self.name} healthy")


@pytest.fixture
def client(tmp_path: Path):
    svc_a = TinyService("a")
    svc_b = TinyService("b")
    lc = Lifecycle(
        [svc_a, svc_b],
        Context(persist=False, data_dir=tmp_path),
    )
    app = build_admin_app(lc)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), svc_a, svc_b


async def test_health(client):
    c, _, _ = client
    r = await c.get("/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["services"].keys()) == {"a", "b"}


async def test_services_list(client):
    c, _, _ = client
    r = await c.get("/_emulator/services")
    assert r.status_code == 200
    body = r.json()
    names = {s["name"] for s in body["services"]}
    assert names == {"a", "b"}


async def test_reset_all(client):
    c, a, b = client
    r = await c.post("/_emulator/reset")
    assert r.status_code == 204
    assert a.resets == 1 and b.resets == 1


async def test_reset_specific(client):
    c, a, b = client
    r = await c.post("/_emulator/reset", params={"service": "b"})
    assert r.status_code == 204
    assert a.resets == 0 and b.resets == 1


async def test_reset_unknown_service_404(client):
    c, _, _ = client
    r = await c.post("/_emulator/reset", params={"service": "nope"})
    assert r.status_code == 404
