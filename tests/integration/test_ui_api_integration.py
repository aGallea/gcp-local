"""End-to-end ui-api flow against a real GCS service with disk persistence."""

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.services.gcs import GcsService


@pytest.fixture
async def integration_client(tmp_path: Path):
    svc = GcsService()
    ctx = Context(persist=True, data_dir=tmp_path)
    lc = Lifecycle([svc], ctx)
    await lc.start_all()
    try:
        app = build_admin_app(lc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await lc.stop_all()


async def test_ui_api_full_lifecycle(integration_client) -> None:
    c = integration_client

    # Create bucket
    r = await c.post("/_emulator/ui-api/v1/gcs/buckets", json={"name": "demo"})
    assert r.status_code == 201

    # Upload blob
    r = await c.post(
        "/_emulator/ui-api/v1/gcs/buckets/demo/blobs",
        files={"file": ("greeting.txt", io.BytesIO(b"hi from gcp-local"), "text/plain")},
    )
    assert r.status_code == 201

    # List blobs
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets/demo/blobs")
    assert r.status_code == 200
    assert [b["name"] for b in r.json()["blobs"]] == ["greeting.txt"]

    # Get metadata + preview
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets/demo/blobs/greeting.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["size"] == 17
    assert body["preview"]["text"] == "hi from gcp-local"

    # Download
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets/demo/blobs/greeting.txt/download")
    assert r.status_code == 200
    assert r.content == b"hi from gcp-local"

    # Delete blob
    r = await c.delete("/_emulator/ui-api/v1/gcs/buckets/demo/blobs/greeting.txt")
    assert r.status_code == 204

    # Delete bucket
    r = await c.delete("/_emulator/ui-api/v1/gcs/buckets/demo")
    assert r.status_code == 204

    # Buckets list now empty
    r = await c.get("/_emulator/ui-api/v1/gcs/buckets")
    assert r.json()["buckets"] == []
