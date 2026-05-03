from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed(svc, names: list[str]) -> None:
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="2026-05-03T10:00:00Z"))
    for n in names:
        await svc.storage.put_object(
            ObjectRecord(
                bucket="b",
                name=n,
                size=len(n),
                generation=1,
                metageneration=1,
                md5_hash="x",
                crc32c="x",
                content_type="text/plain",
                time_created="2026-05-03T10:01:00Z",
                updated="2026-05-03T10:01:00Z",
            ),
            n.encode(),
        )


async def test_list_blobs_flat(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, ["a.txt", "b.txt"])
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs")
    assert r.status_code == 200
    body = r.json()
    assert body["bucket"] == "b"
    assert body["prefix"] == ""
    assert {x["name"] for x in body["blobs"]} == {"a.txt", "b.txt"}
    assert body["folders"] == []


async def test_list_blobs_with_prefix_and_delimiter_returns_folders(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc, ["a.txt", "logs/2026/01.log", "logs/2026/02.log", "logs/2025/12.log"])
    r = await client.get(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        params={"prefix": "logs/", "delimiter": "/"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prefix"] == "logs/"
    assert body["blobs"] == []  # Everything under logs/ is itself prefixed by another /
    assert sorted(body["folders"]) == ["logs/2025/", "logs/2026/"]


async def test_list_blobs_unknown_bucket_404(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/missing/blobs")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
