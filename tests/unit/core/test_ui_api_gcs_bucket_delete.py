from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


async def _seed_bucket(svc, name="b") -> None:
    await svc.storage.create_bucket(BucketMeta(name=name, time_created="2026-05-03T10:00:00Z"))


async def _seed_object(svc, bucket="b", name="x") -> None:
    await svc.storage.put_object(
        ObjectRecord(
            bucket=bucket,
            name=name,
            size=3,
            generation=1,
            metageneration=1,
            md5_hash="x",
            crc32c="x",
            time_created="2026-05-03T10:01:00Z",
            updated="2026-05-03T10:01:00Z",
        ),
        b"abc",
    )


async def test_delete_empty_bucket(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b")
    assert r.status_code == 204
    assert await svc.storage.list_buckets() == []


async def test_delete_unknown_bucket_404(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_delete_non_empty_bucket_without_force_returns_409(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    await _seed_object(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_empty"


async def test_delete_non_empty_bucket_with_force_succeeds(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    await _seed_object(svc)
    r = await client.delete("/_emulator/ui-api/v1/gcs/buckets/b?force=true")
    assert r.status_code == 204
    assert await svc.storage.list_buckets() == []
