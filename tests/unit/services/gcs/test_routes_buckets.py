from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


@pytest.fixture
def app(tmp_path: Path):
    storage = InMemoryStorage()
    hub = StateHub()
    gen = GenerationCounter()
    app = FastAPI()
    app.include_router(build_router(storage=storage, state_hub=hub, generations=gen))
    return app


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_create_bucket(client):
    r = await client.post("/storage/v1/b", json={"name": "mybucket"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "mybucket"
    assert body["metageneration"] == 1


async def test_create_duplicate_bucket_409(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    r = await client.post("/storage/v1/b", json={"name": "b"})
    assert r.status_code == 409
    assert r.json()["error"]["errors"][0]["reason"] == "conflict"


async def test_get_bucket(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    r = await client.get("/storage/v1/b/b")
    assert r.status_code == 200
    assert r.json()["name"] == "b"


async def test_get_missing_bucket_404(client):
    r = await client.get("/storage/v1/b/nope")
    assert r.status_code == 404
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


async def test_list_buckets(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    await client.post("/storage/v1/b", json={"name": "a"})
    r = await client.get("/storage/v1/b")
    assert r.status_code == 200
    names = [b["name"] for b in r.json()["items"]]
    assert names == ["a", "b"]


async def test_delete_bucket(client):
    await client.post("/storage/v1/b", json={"name": "b"})
    r = await client.delete("/storage/v1/b/b")
    assert r.status_code == 204
    r2 = await client.get("/storage/v1/b/b")
    assert r2.status_code == 404


async def test_delete_missing_bucket_404(client):
    r = await client.delete("/storage/v1/b/nope")
    assert r.status_code == 404
