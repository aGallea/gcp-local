from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import (
    EVENT_DELETE,
    EVENT_FINALIZE,
    EVENT_METADATA_UPDATE,
    build_event_payload,
    publish_delete,
    publish_finalize,
    publish_metadata_update,
)
from gcp_local.services.gcs.models import ObjectRecord


def make_rec() -> ObjectRecord:
    return ObjectRecord(
        bucket="b", name="o", size=10,
        generation=1, metageneration=1,
        content_type="text/plain",
        md5_hash="abc", crc32c="xyz",
        time_created="2026-04-24T00:00:00Z",
        updated="2026-04-24T00:00:00Z",
        metadata={"k": "v"},
    )


def test_build_event_payload_contract() -> None:
    payload = build_event_payload(make_rec())
    assert payload == {
        "bucket": "b",
        "name": "o",
        "generation": 1,
        "metageneration": 1,
        "size": 10,
        "contentType": "text/plain",
        "md5Hash": "abc",
        "crc32c": "xyz",
        "timeCreated": "2026-04-24T00:00:00Z",
        "updated": "2026-04-24T00:00:00Z",
        "metadata": {"k": "v"},
    }


async def test_publish_finalize() -> None:
    hub = StateHub()
    got: list[dict[str, object]] = []

    async def h(ev: dict[str, object]) -> None:
        got.append(ev)

    hub.subscribe(EVENT_FINALIZE, h)
    await publish_finalize(hub, make_rec())
    assert len(got) == 1
    assert got[0]["bucket"] == "b" and got[0]["name"] == "o"


async def test_publish_metadata_update() -> None:
    hub = StateHub()
    got: list[dict[str, object]] = []

    async def h(ev: dict[str, object]) -> None:
        got.append(ev)

    hub.subscribe(EVENT_METADATA_UPDATE, h)
    await publish_metadata_update(hub, make_rec())
    assert len(got) == 1


async def test_publish_delete() -> None:
    hub = StateHub()
    got: list[dict[str, object]] = []

    async def h(ev: dict[str, object]) -> None:
        got.append(ev)

    hub.subscribe(EVENT_DELETE, h)
    await publish_delete(hub, make_rec())
    assert len(got) == 1


async def test_publish_without_hub_is_noop() -> None:
    # hub=None should be accepted and silent
    await publish_finalize(None, make_rec())
    await publish_metadata_update(None, make_rec())
    await publish_delete(None, make_rec())
