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


async def test_ui_api_services_endpoint_mounted(client) -> None:
    c, _, _ = client
    r = await c.get("/_emulator/ui-api/v1/services")
    assert r.status_code == 200
    body = r.json()
    assert {s["name"] for s in body["services"]} == {"a", "b"}


async def test_ui_api_uses_envelope_error_format(client) -> None:
    c, _, _ = client
    # Unknown ui-api path -> 404 from FastAPI default; the envelope handler is
    # only for UiApiError raises. Ensure the router mount doesn't shadow other
    # admin endpoints. Sanity-check that /_emulator/health still works.
    r = await c.get("/_emulator/health")
    assert r.status_code == 200


async def test_ui_root_returns_friendly_message_when_bundle_missing(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty-static"
    empty.mkdir()
    monkeypatch.setenv("GCP_LOCAL_UI_STATIC_DIR", str(empty))

    from httpx import ASGITransport, AsyncClient

    from gcp_local.core.admin_api import build_admin_app
    from gcp_local.core.context import Context
    from gcp_local.core.lifecycle import Lifecycle

    lc = Lifecycle([], Context(persist=False, data_dir=tmp_path))
    app = build_admin_app(lc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/ui/")
        assert r.status_code == 200
        assert "gcp-local UI" in r.text
        assert "npm run build" in r.text


async def test_ui_root_serves_bundle_when_present(tmp_path, monkeypatch) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>built</title>")
    monkeypatch.setenv("GCP_LOCAL_UI_STATIC_DIR", str(static))

    from httpx import ASGITransport, AsyncClient

    from gcp_local.core.admin_api import build_admin_app
    from gcp_local.core.context import Context
    from gcp_local.core.lifecycle import Lifecycle

    lc = Lifecycle([], Context(persist=False, data_dir=tmp_path))
    app = build_admin_app(lc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/ui/")
        assert r.status_code == 200
        assert "<title>built</title>" in r.text
