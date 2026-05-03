from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed(svc, name="hi.txt") -> None:
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await svc.storage.put_object(
        ObjectRecord(
            bucket="b",
            name=name,
            size=2,
            generation=1,
            metageneration=1,
            md5_hash="m",
            crc32c="c",
            time_created="t",
            updated="t",
        ),
        b"hi",
    )


async def test_delete_blob(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b/blobs/hi.txt")
    assert r.status_code == 204
    objs, _ = await svc.storage.list_objects_with_prefixes("b")
    assert objs == []


async def test_delete_unknown_blob_404(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b/blobs/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
