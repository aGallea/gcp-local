import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import EVENT_METADATA_UPDATE
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def rec(name="o", bucket="b", gen=5, mgen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket,
        name=name,
        size=3,
        generation=gen,
        metageneration=mgen,
        content_type="text/plain",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
        metadata={"x": "1"},
    )


@pytest.fixture
async def wired():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await storage.put_object(rec(), b"abc")
    hub = StateHub()
    events: list[dict] = []

    async def cap(ev):
        events.append(ev)

    hub.subscribe(EVENT_METADATA_UPDATE, cap)
    app = FastAPI()
    app.include_router(
        build_router(storage=storage, state_hub=hub, generations=GenerationCounter())
    )
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), storage, events


async def test_patch_metadata_increments_metageneration(wired):
    c, storage, events = wired
    r = await c.patch(
        "/storage/v1/b/b/o/o",
        json={"metadata": {"x": "1", "y": "2"}, "contentType": "application/xml"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"] == {"x": "1", "y": "2"}
    assert body["contentType"] == "application/xml"
    assert body["generation"] == 5
    assert body["metageneration"] == 2
    got = await storage.get_object("b", "o")
    assert got.metageneration == 2
    assert len(events) == 1


async def test_patch_with_metageneration_precondition_match(wired):
    c, _, _ = wired
    r = await c.patch(
        "/storage/v1/b/b/o/o",
        json={"metadata": {"y": "2"}},
        params={"ifMetagenerationMatch": 1},
    )
    assert r.status_code == 200


async def test_patch_with_metageneration_precondition_mismatch(wired):
    c, _, _ = wired
    r = await c.patch(
        "/storage/v1/b/b/o/o",
        json={"metadata": {"y": "2"}},
        params={"ifMetagenerationMatch": 99},
    )
    assert r.status_code == 412


async def test_patch_missing_object_404(wired):
    c, _, _ = wired
    r = await c.patch(
        "/storage/v1/b/b/o/missing",
        json={"metadata": {"x": "1"}},
    )
    assert r.status_code == 404
