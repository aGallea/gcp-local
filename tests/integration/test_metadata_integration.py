"""End-to-end tests for the metadata server using real google-auth."""

import asyncio
import base64
import json

import google.auth
import google.auth.compute_engine._metadata as _gce_metadata
import pytest
from google.auth import compute_engine
from google.auth.transport import requests as ga_requests


@pytest.fixture(autouse=True)
def _point_google_auth_at_emulator(
    emulator: dict[str, int], monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Make google-auth treat the local metadata server as the GCE metadata server.

    google-auth resolves GCE_METADATA_HOST at module import time into the
    module-level variable ``_GCE_METADATA_HOST``.  Setting the env-var alone
    after import has no effect, so we patch the module attribute directly.
    GCE_METADATA_IP is read at call time via os.getenv, so the env-var is
    enough for that path.

    CLOUDSDK_CONFIG is pointed at an empty tmp dir so that gcloud application
    default credentials do not intercept ``google.auth.default()`` on machines
    where the developer has run ``gcloud auth application-default login``.
    """
    metadata_host = f"127.0.0.1:{emulator['metadata_port']}"
    monkeypatch.setattr(_gce_metadata, "_GCE_METADATA_HOST", metadata_host)
    monkeypatch.setenv("GCE_METADATA_IP", metadata_host)
    # Prevent ADC from falling back to user creds during the test.
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    # Prevent gcloud SDK ADC from intercepting google.auth.default().
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))


@pytest.mark.asyncio
async def test_compute_engine_credentials_refresh_against_emulator(
    emulator: dict[str, int],
) -> None:
    def _refresh() -> compute_engine.Credentials:
        creds = compute_engine.Credentials()
        creds.refresh(ga_requests.Request())
        return creds

    creds = await asyncio.get_running_loop().run_in_executor(None, _refresh)
    assert creds.token == "ya29.gcp-local-stub-token"
    assert creds.service_account_email.endswith("local-dev.iam.gserviceaccount.com")


@pytest.mark.asyncio
async def test_google_auth_default_picks_metadata_server() -> None:
    def _default():
        return google.auth.default()

    creds, project = await asyncio.get_running_loop().run_in_executor(None, _default)
    assert isinstance(creds, compute_engine.Credentials)
    assert project == "local-dev"


@pytest.mark.asyncio
async def test_id_token_audience_round_trip(emulator: dict[str, int]) -> None:
    def _get_id_token() -> str:
        creds = compute_engine.IDTokenCredentials(
            ga_requests.Request(),
            target_audience="https://service.example/api",
            use_metadata_identity_endpoint=True,
        )
        creds.refresh(ga_requests.Request())
        return creds.token

    token = await asyncio.get_running_loop().run_in_executor(None, _get_id_token)
    parts = token.split(".")
    assert len(parts) == 3
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    assert payload["aud"] == "https://service.example/api"
    assert payload["email"].endswith("local-dev.iam.gserviceaccount.com")


@pytest.mark.asyncio
async def test_bigquery_client_works_with_plain_adc(emulator: dict[str, int]) -> None:
    """Production-shaped client code (no AnonymousCredentials, no client_options)
    must complete a query against gcp-local. The metadata server keeps ADC
    happy; BIGQUERY_EMULATOR_HOST routes traffic to the BigQuery emulator.
    """
    import os

    from google.cloud import bigquery

    os.environ["BIGQUERY_EMULATOR_HOST"] = f"http://127.0.0.1:{emulator['bigquery_port']}"
    try:

        def _query() -> list:
            client = bigquery.Client(project="local-dev")
            return list(client.query("SELECT 1 AS x").result())

        rows = await asyncio.get_running_loop().run_in_executor(None, _query)
        assert [r["x"] for r in rows] == [1]
    finally:
        os.environ.pop("BIGQUERY_EMULATOR_HOST", None)
