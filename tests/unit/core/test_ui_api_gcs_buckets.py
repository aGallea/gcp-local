from gcp_local.services.gcs.models import BucketMeta


async def test_list_buckets_empty(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets")
    assert r.status_code == 200
    assert r.json() == {"buckets": []}


async def test_list_buckets_returns_seeded(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await svc.storage.create_bucket(
        BucketMeta(name="alpha", time_created="2026-05-03T10:00:00Z", location="US")
    )
    await svc.storage.create_bucket(
        BucketMeta(name="beta", time_created="2026-05-03T10:01:00Z", location="EU")
    )
    r = await client.get("/_emulator/ui-api/v1/gcs/buckets")
    assert r.status_code == 200
    body = r.json()
    names = [b["name"] for b in body["buckets"]]
    assert names == ["alpha", "beta"]
    assert body["buckets"][1]["location"] == "EU"
