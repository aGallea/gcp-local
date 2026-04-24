import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def rec(name="o", bucket="b", size=5, gen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket,
        name=name,
        size=size,
        generation=gen,
        metageneration=1,
        content_type="text/plain",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )


@pytest.fixture
async def client():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="src", time_created="t"))
    await storage.create_bucket(BucketMeta(name="dst", time_created="t"))
    await storage.put_object(rec(bucket="src", name="hello.txt"), b"hello")
    await storage.put_object(rec(bucket="src", name="part1", size=3), b"abc")
    await storage.put_object(rec(bucket="src", name="part2", size=3), b"def")
    app = FastAPI()
    app.include_router(
        build_router(storage=storage, state_hub=StateHub(), generations=GenerationCounter())
    )
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), storage


async def test_copy_object(client):
    c, storage = client
    r = await c.post(
        "/storage/v1/b/src/o/hello.txt/copyTo/b/dst/o/copied.txt",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "copied.txt"
    assert body["bucket"] == "dst"
    stored = await storage.get_object_bytes("dst", "copied.txt")
    assert stored == b"hello"


async def test_copy_missing_source_404(client):
    c, _ = client
    r = await c.post(
        "/storage/v1/b/src/o/nope/copyTo/b/dst/o/copied.txt",
    )
    assert r.status_code == 404


async def test_compose_object(client):
    c, storage = client
    r = await c.post(
        "/storage/v1/b/src/o/combined/compose",
        json={
            "sourceObjects": [{"name": "part1"}, {"name": "part2"}],
            "destination": {"contentType": "text/plain"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "combined"
    stored = await storage.get_object_bytes("src", "combined")
    assert stored == b"abcdef"


async def test_compose_too_many_sources_400(client):
    c, _ = client
    r = await c.post(
        "/storage/v1/b/src/o/big/compose",
        json={"sourceObjects": [{"name": "part1"}] * 33},
    )
    assert r.status_code == 400


async def test_compose_missing_source_404(client):
    c, _ = client
    r = await c.post(
        "/storage/v1/b/src/o/combined/compose",
        json={"sourceObjects": [{"name": "part1"}, {"name": "nope"}]},
    )
    assert r.status_code == 404
