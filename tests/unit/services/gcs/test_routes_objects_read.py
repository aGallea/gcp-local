import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def rec(name="o", bucket="b", size=5, gen=1, mgen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket,
        name=name,
        size=size,
        generation=gen,
        metageneration=mgen,
        content_type="text/plain",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )


@pytest.fixture
async def client():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await storage.put_object(rec(name="hello.txt", size=5), b"hello")
    await storage.put_object(rec(name="dir/a.log", size=3), b"abc")
    await storage.put_object(rec(name="dir/b.log", size=3), b"def")
    await storage.put_object(rec(name="z", size=1), b"z")

    app = FastAPI()
    app.include_router(
        build_router(storage=storage, state_hub=StateHub(), generations=GenerationCounter())
    )
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), storage


async def test_get_object_metadata(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/hello.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 5


async def test_get_object_bytes_alt_media(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/hello.txt", params={"alt": "media"})
    assert r.status_code == 200
    assert r.content == b"hello"


async def test_get_object_bytes_ranged(client):
    c, _ = client
    r = await c.get(
        "/storage/v1/b/b/o/hello.txt",
        params={"alt": "media"},
        headers={"Range": "bytes=1-3"},
    )
    assert r.status_code == 206
    assert r.content == b"ell"
    assert r.headers["content-range"] == "bytes 1-3/5"


async def test_get_object_range_unsatisfiable(client):
    c, _ = client
    r = await c.get(
        "/storage/v1/b/b/o/hello.txt",
        params={"alt": "media"},
        headers={"Range": "bytes=100-200"},
    )
    assert r.status_code == 416


async def test_get_object_with_nested_name(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/dir/a.log")
    assert r.status_code == 200
    assert r.json()["name"] == "dir/a.log"


async def test_get_object_404(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o/nope")
    assert r.status_code == 404


async def test_list_objects(client):
    c, _ = client
    r = await c.get("/storage/v1/b/b/o")
    assert r.status_code == 200
    names = [o["name"] for o in r.json()["items"]]
    assert names == ["dir/a.log", "dir/b.log", "hello.txt", "z"]


async def test_list_objects_prefix_and_delimiter(client):
    c, _ = client
    r = await c.get(
        "/storage/v1/b/b/o",
        params={"prefix": "", "delimiter": "/"},
    )
    body = r.json()
    item_names = [o["name"] for o in body.get("items", [])]
    prefixes = body.get("prefixes", [])
    assert set(item_names) == {"hello.txt", "z"}
    assert prefixes == ["dir/"]


async def test_list_objects_pagination(client):
    c, _ = client
    r1 = await c.get("/storage/v1/b/b/o", params={"maxResults": 2})
    body1 = r1.json()
    assert len(body1["items"]) == 2
    assert "nextPageToken" in body1
    r2 = await c.get(
        "/storage/v1/b/b/o",
        params={"maxResults": 2, "pageToken": body1["nextPageToken"]},
    )
    body2 = r2.json()
    assert len(body2["items"]) == 2


async def test_delete_object(client):
    c, _ = client
    r = await c.delete("/storage/v1/b/b/o/hello.txt")
    assert r.status_code == 204
    r2 = await c.get("/storage/v1/b/b/o/hello.txt")
    assert r2.status_code == 404


async def test_delete_missing_object_404(client):
    c, _ = client
    r = await c.delete("/storage/v1/b/b/o/nope")
    assert r.status_code == 404
