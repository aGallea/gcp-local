import io

from gcp_local.services.gcs.models import BucketMeta


async def _seed_bucket(svc) -> None:
    await svc.storage.create_bucket(BucketMeta(name="b", time_created="2026-05-03T10:00:00Z"))


async def test_upload_creates_blob(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        files={"file": ("hello.txt", io.BytesIO(b"hi there"), "text/plain")},
        data={"name": "hello.txt"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == 8
    record = await svc.storage.get_object("b", "hello.txt")
    assert record.size == 8
    assert (await svc.storage.get_object_bytes("b", "hello.txt")) == b"hi there"


async def test_upload_uses_filename_when_name_missing(gcs_ui_client) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        files={"file": ("auto.txt", io.BytesIO(b"hi"), "text/plain")},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "auto.txt"


async def test_upload_unknown_bucket_404(gcs_ui_client) -> None:
    client, _ = gcs_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/missing/blobs",
        files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_upload_too_large_returns_413(gcs_ui_client, monkeypatch) -> None:
    client, svc = gcs_ui_client
    await _seed_bucket(svc)
    monkeypatch.setenv("GCP_LOCAL_UI_MAX_UPLOAD_MB", "0")  # cap = 0 MB -> any file too large
    r = await client.post(
        "/_emulator/ui-api/v1/gcs/buckets/b/blobs",
        files={"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
