"""Route-level tests for the metadata server."""

import httpx
import pytest

from gcp_local.services.metadata.app import build_app

DEFAULT_EMAIL = "default@local-dev.iam.gserviceaccount.com"


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


async def test_service_accounts_listing_includes_default_and_configured_email(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body_lines = resp.text.strip().splitlines()
    assert "default/" in body_lines
    assert f"{DEFAULT_EMAIL}/" in body_lines


async def test_email_endpoint_returns_configured_email(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.text == DEFAULT_EMAIL


async def test_email_endpoint_works_for_email_alias(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METADATA_SERVICE_ACCOUNT_EMAIL", "bot@x.iam.gserviceaccount.com")
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/bot@x.iam.gserviceaccount.com/email",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.text == "bot@x.iam.gserviceaccount.com"


async def test_email_endpoint_rejects_unknown_alias_with_404(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/nobody/email",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 404


async def test_scopes_endpoint_default_returns_cloud_platform(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/scopes",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.text.strip() == "https://www.googleapis.com/auth/cloud-platform"


async def test_scopes_endpoint_honors_env(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "METADATA_SCOPES",
        "https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/cloud-platform",
    )
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/scopes",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text.splitlines() == [
        "https://www.googleapis.com/auth/devstorage.read_only",
        "https://www.googleapis.com/auth/cloud-platform",
    ]


async def test_recursive_view_returns_email_aliases_and_scopes(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/?recursive=true",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == DEFAULT_EMAIL
    assert "default" in body["aliases"]
    assert body["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]


async def test_token_endpoint_returns_stub_access_token(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["access_token"] == "ya29.gcp-local-stub-token"
    assert body["expires_in"] == 3600
    assert body["token_type"] == "Bearer"


async def test_token_endpoint_accepts_and_ignores_scopes_query(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/token?scopes=a,b",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "ya29.gcp-local-stub-token"


async def test_token_endpoint_rejects_unknown_alias_with_404(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/nobody/token",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 404
