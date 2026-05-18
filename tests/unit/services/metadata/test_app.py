"""Route-level tests for the metadata server."""

import httpx
import pytest

from gcp_local.services.metadata.app import build_app


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app()), base_url="http://meta")


async def test_request_without_metadata_flavor_header_is_rejected_with_403(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get("/")
    assert resp.status_code == 403
    assert "Metadata-Flavor" in resp.text


async def test_response_always_includes_metadata_flavor_google_header(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get("/", headers={"Metadata-Flavor": "Google"})
    assert resp.status_code == 200
    assert resp.headers["Metadata-Flavor"] == "Google"


async def test_403_response_also_includes_metadata_flavor_header(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get("/")
    assert resp.headers["Metadata-Flavor"] == "Google"


async def test_project_id_default_is_local_dev(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "local-dev"


async def test_project_id_honors_GOOGLE_CLOUD_PROJECT_env(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text == "my-proj"


async def test_numeric_project_id_default_is_zero(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/numeric-project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text == "0"


async def test_numeric_project_id_honors_env(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METADATA_NUMERIC_PROJECT_ID", "1234567890")
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/numeric-project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text == "1234567890"
