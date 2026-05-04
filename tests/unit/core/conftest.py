"""Shared fixtures for ui-api tests.

Provides a fully-wired admin app whose only running service is GCS in
in-memory mode, plus a real ``GcsStorage`` so tests can seed state.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.services.gcs import GcsService


@pytest.fixture
async def gcs_ui_client(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, GcsService]]:
    svc = GcsService()
    ctx = Context(persist=False, data_dir=tmp_path)
    lc = Lifecycle([svc], ctx)
    await lc.start_all()
    try:
        app = build_admin_app(lc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, svc
    finally:
        await lc.stop_all()
