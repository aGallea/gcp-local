"""End-to-end tests for the metadata server using real google-auth."""

import asyncio

import google.auth.compute_engine._metadata as _gce_metadata
import pytest
from google.auth import compute_engine
from google.auth.transport import requests as ga_requests


@pytest.fixture(autouse=True)
def _point_google_auth_at_emulator(
    emulator: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make google-auth treat the local metadata server as the GCE metadata server.

    google-auth resolves GCE_METADATA_HOST at module import time into the
    module-level variable ``_GCE_METADATA_HOST``.  Setting the env-var alone
    after import has no effect, so we patch the module attribute directly.
    GCE_METADATA_IP is read at call time via os.getenv, so the env-var is
    enough for that path.
    """
    metadata_host = f"127.0.0.1:{emulator['metadata_port']}"
    monkeypatch.setattr(_gce_metadata, "_GCE_METADATA_HOST", metadata_host)
    monkeypatch.setenv("GCE_METADATA_IP", metadata_host)
    # Prevent ADC from falling back to user creds during the test.
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)


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
