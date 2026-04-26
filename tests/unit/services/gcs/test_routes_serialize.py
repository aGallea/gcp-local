"""Regression tests for the JSON-API fields gcloud requires.

Real GCS responses include ``kind``, ``id``, ``selfLink``, and ``mediaLink``.
The ``google-cloud-storage`` Python library tolerates their absence, but
``gcloud storage`` (which goes through apitools) crashes with a bytes/str
``TypeError`` when ``mediaLink`` is missing — its download path threads the
value through ``urllib.parse.urlsplit`` which coerces ``None`` into bytes.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def _rec(name: str, bucket: str = "b", *, gen: int = 1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket,
        name=name,
        size=5,
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
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await storage.put_object(_rec("hello.txt"), b"hello")
    await storage.put_object(_rec("dir/a.log"), b"abc")

    app = FastAPI()
    app.include_router(
        build_router(storage=storage, state_hub=StateHub(), generations=GenerationCounter())
    )
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://emulator:9023")


async def test_get_object_includes_media_link_and_self_link(client):
    r = await client.get("/storage/v1/b/b/o/hello.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "storage#object"
    assert body["id"] == "b/hello.txt/1"
    assert body["selfLink"] == "http://emulator:9023/storage/v1/b/b/o/hello.txt"
    assert body["mediaLink"] == (
        "http://emulator:9023/download/storage/v1/b/b/o/hello.txt?generation=1&alt=media"
    )
    assert body["storageClass"] == "STANDARD"


async def test_get_object_url_encodes_slash_in_name(client):
    """gcloud constructs requests with %2F for path segments inside the name."""
    r = await client.get("/storage/v1/b/b/o/dir%2Fa.log")
    assert r.status_code == 200
    body = r.json()
    # name is the raw form; selfLink and mediaLink quote slashes back to %2F
    # because they refer to a path *segment*, not a directory boundary.
    assert body["name"] == "dir/a.log"
    assert body["selfLink"].endswith("/o/dir%2Fa.log")
    assert "dir%2Fa.log?generation=1&alt=media" in body["mediaLink"]


async def test_list_objects_each_item_has_media_link(client):
    r = await client.get("/storage/v1/b/b/o")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "storage#objects"
    assert len(body["items"]) >= 1
    for item in body["items"]:
        assert item["kind"] == "storage#object"
        assert item["mediaLink"].startswith("http://emulator:9023/download/storage/v1/b/")


async def test_get_bucket_includes_self_link(client):
    r = await client.get("/storage/v1/b/b")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "storage#bucket"
    assert body["id"] == "b"
    assert body["selfLink"] == "http://emulator:9023/storage/v1/b/b"


async def test_storage_layout_endpoint(client):
    """gcloud probes this endpoint as a preflight — must not 404."""
    r = await client.get("/storage/v1/b/b/storageLayout")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "storage#storageLayout"
    assert body["bucket"] == "b"
    assert body["location"] == "US"
    assert body["locationType"] == "multi-region"
    assert body["hierarchicalNamespace"] == {"enabled": False}


async def test_storage_layout_unknown_bucket_404(client):
    r = await client.get("/storage/v1/b/no-such-bucket/storageLayout")
    assert r.status_code == 404
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"
