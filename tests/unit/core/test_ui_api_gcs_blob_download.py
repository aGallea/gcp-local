from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def test_download_returns_bytes_with_content_type(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await svc.storage.put_object(
        ObjectRecord(
            bucket="b",
            name="hi.txt",
            size=2,
            generation=1,
            metageneration=1,
            md5_hash="m",
            crc32c="c",
            content_type="text/plain",
            time_created="t",
            updated="t",
        ),
        b"hi",
    )
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/hi.txt/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"] == 'attachment; filename="hi.txt"'
    assert r.content == b"hi"


async def test_download_unknown_blob_404(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="t"))
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets/b/blobs/nope/download")
    assert r.status_code == 404
