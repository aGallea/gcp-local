import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import EVENT_FINALIZE
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


@pytest.fixture
async def wired():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    hub = StateHub()
    app = FastAPI()
    app.include_router(
        build_router(storage=storage, state_hub=hub, generations=GenerationCounter())
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    events: list[dict] = []

    async def capture(ev):
        events.append(ev)

    hub.subscribe(EVENT_FINALIZE, capture)
    yield client, storage, events


async def test_simple_upload(wired):
    c, storage, events = wired
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "hello.txt"},
        content=b"hello",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 5
    assert body["generation"] == 1
    assert body["md5Hash"] == "XUFAKrxLKna5cZ2REBfFkg=="
    assert body["crc32c"] == "mnG7TA=="
    assert body["contentType"] == "text/plain"
    stored = await storage.get_object_bytes("b", "hello.txt")
    assert stored == b"hello"
    assert len(events) == 1
    assert events[0]["name"] == "hello.txt"


async def test_simple_upload_overwrite_increments_generation(wired):
    c, _, _ = wired
    await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o"},
        content=b"v1",
        headers={"Content-Type": "text/plain"},
    )
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o"},
        content=b"v2-longer",
        headers={"Content-Type": "text/plain"},
    )
    body = r.json()
    assert body["generation"] == 2


async def test_multipart_upload(wired):
    c, _, _ = wired
    boundary = "===GCSBOUNDARY==="
    meta = json.dumps(
        {"name": "doc.txt", "contentType": "text/markdown", "metadata": {"author": "asaf"}}
    )
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/markdown\r\n\r\n"
        f"# hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    assert r.status_code == 200
    body_json = r.json()
    assert body_json["name"] == "doc.txt"
    assert body_json["contentType"] == "text/markdown"
    assert body_json["metadata"] == {"author": "asaf"}


async def test_precondition_if_generation_match_zero_blocks_overwrite(wired):
    c, _, _ = wired
    await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o"},
        content=b"a",
        headers={"Content-Type": "text/plain"},
    )
    r = await c.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "o", "ifGenerationMatch": "0"},
        content=b"b",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 412
    assert r.json()["error"]["errors"][0]["reason"] == "conditionNotMet"
