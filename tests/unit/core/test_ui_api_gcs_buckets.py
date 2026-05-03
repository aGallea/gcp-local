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


async def test_create_bucket_creates_and_returns_summary(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets", json={"name": "new-bucket", "location": "EU"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "new-bucket"
    assert body["location"] == "EU"
    # Verify storage actually has it.
    buckets = await svc.storage.list_buckets()
    assert [b.name for b in buckets] == ["new-bucket"]


async def test_create_bucket_conflict_returns_envelope(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    from gcp_local.services.gcs.models import BucketMeta

    await svc.storage.create_bucket(BucketMeta(name="dup", time_created="2026-05-03T10:00:00Z"))
    r = await client.post("/_emulator/ui-api/v1/gcs/buckets", json={"name": "dup"})
    assert r.status_code == 409
    assert r.json() == {
        "error": {"code": "already_exists", "message": "bucket 'dup' already exists"}
    }


async def test_create_bucket_invalid_name_returns_400(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    # Pydantic enforces "name" as a string; an empty string is allowed by the schema
    # but the storage layer or our validator rejects it.
    r = await client.post("/_emulator/ui-api/v1/gcs/buckets", json={"name": ""})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_argument"
