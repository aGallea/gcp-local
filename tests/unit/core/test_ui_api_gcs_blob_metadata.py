import base64

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed(svc, name: str, content: bytes, content_type: str) -> None:
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await svc.storage.put_object(
        ObjectRecord(
            bucket="b",
            name=name,
            size=len(content),
            generation=1,
            metageneration=1,
            md5_hash="m",
            crc32c="c",
            content_type=content_type,
            time_created="2026-05-03T10:00:00Z",
            updated="2026-05-03T10:00:00Z",
        ),
        content,
    )


async def test_metadata_text_preview(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, "hello.txt", b"hi there", "text/plain")
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/hello.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 8
    assert body["preview"] == {
        "kind": "text",
        "text": "hi there",
        "image_data_url": None,
        "truncated": False,
        "reason": None,
    }


async def test_metadata_json_preview(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, "x.json", b'{"a":1}', "application/json")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/x.json")).json()
    assert body["preview"]["kind"] == "json"
    assert body["preview"]["text"] == '{"a":1}'


async def test_metadata_image_preview(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    raw = b"\x89PNG\r\n\x1a\nfakeimage"
    await _seed(svc, "p.png", raw, "image/png")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/p.png")).json()
    assert body["preview"]["kind"] == "image"
    assert body["preview"]["image_data_url"] == (
        "data:image/png;base64," + base64.b64encode(raw).decode()
    )


async def test_metadata_text_truncated_when_over_cap(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    big = b"a" * (1024 * 1024 + 100)  # > 1 MB cap
    await _seed(svc, "big.txt", big, "text/plain")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/big.txt")).json()
    assert body["preview"]["kind"] == "text"
    assert body["preview"]["truncated"] is True
    assert len(body["preview"]["text"].encode()) == 1024 * 1024


async def test_metadata_no_preview_for_unknown_type(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, "x.bin", b"\x00\x01", "application/octet-stream")
    body = (await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/x.bin")).json()
    assert body["preview"]["kind"] == "none"
    assert body["preview"]["reason"]


async def test_metadata_unknown_blob_404(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
