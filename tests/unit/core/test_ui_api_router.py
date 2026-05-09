from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcp_local.core.service import HealthStatus, Port
from gcp_local.core.ui_api.router import build_ui_api_router


class TinyService:
    def __init__(self, name: str, ports: list[Port]) -> None:
        self.name = name
        self.default_ports = ports

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, message="ok")


class FakeLifecycle:
    def __init__(self, services: list) -> None:
        self.services = services


def _client(lc) -> TestClient:
    app = FastAPI()
    app.include_router(build_ui_api_router(lc))
    return TestClient(app)


def test_services_endpoint_lists_services() -> None:
    lc = FakeLifecycle(
        [
            TinyService("gcs", [Port(4443, "rest")]),
            TinyService("bigquery", [Port(9050, "rest")]),
        ]
    )
    r = _client(lc).get("/_emulator/ui-api/v1/services")
    assert r.status_code == 200
    body = r.json()
    assert {s["name"] for s in body["services"]} == {"gcs", "bigquery"}
    gcs = next(s for s in body["services"] if s["name"] == "gcs")
    assert gcs["ports"] == [{"number": 4443, "protocol": "rest"}]
    assert gcs["ui_supported"] is True  # GCS UI ships
    bq = next(s for s in body["services"] if s["name"] == "bigquery")
    assert bq["ui_supported"] is True  # BigQuery UI ships
    assert isinstance(body["version"], str) and body["version"]


def test_unsupported_service_marked_false() -> None:
    lc = FakeLifecycle([TinyService("pubsub", [Port(8085, "rest")])])
    r = _client(lc).get("/_emulator/ui-api/v1/services")
    svc = r.json()["services"][0]
    assert svc["ui_supported"] is False
