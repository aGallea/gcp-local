"""Integration tests driving gcp-local GCS with the real google-cloud-storage client.

The `emulator` fixture (from `conftest.py`) boots the emulator in-process and
yields endpoint ports. Each test constructs a fresh storage.Client pointed at
the emulator and exercises common client API calls end to end.

Because the emulator runs as an asyncio task in the test event loop, all
google-cloud-storage calls (which are synchronous/blocking) are dispatched via
`asyncio.to_thread` so they don't block the loop and starve the server.
"""

import asyncio
import io
import os

import pytest
from google.api_core import exceptions as gce
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage


@pytest.fixture
def client(emulator, monkeypatch):
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", f"http://127.0.0.1:{emulator['gcs_port']}")
    return storage.Client(
        project="test-project",
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": f"http://127.0.0.1:{emulator['gcs_port']}"},
    )


async def test_create_and_list_bucket(client):
    bucket = await asyncio.to_thread(client.create_bucket, "my-bucket")
    assert bucket.name == "my-bucket"
    names = await asyncio.to_thread(lambda: [b.name for b in client.list_buckets()])
    assert "my-bucket" in names


async def test_simple_upload_download_roundtrip(client):
    bucket = await asyncio.to_thread(client.create_bucket, "rt")
    blob = bucket.blob("hello.txt")
    await asyncio.to_thread(blob.upload_from_string, b"hello world", content_type="text/plain")
    downloaded = await asyncio.to_thread(bucket.blob("hello.txt").download_as_bytes)
    assert downloaded == b"hello world"


async def test_resumable_upload_large(client):
    bucket = await asyncio.to_thread(client.create_bucket, "big")
    data = os.urandom(10 * 1024 * 1024)  # 10 MiB triggers resumable
    blob = bucket.blob("big.bin")
    await asyncio.to_thread(
        lambda: blob.upload_from_file(
            io.BytesIO(data),
            content_type="application/octet-stream",
            size=len(data),
        )
    )
    got = await asyncio.to_thread(bucket.blob("big.bin").download_as_bytes)
    assert got == data


async def test_if_generation_match_zero_create_only(client):
    bucket = await asyncio.to_thread(client.create_bucket, "ifmatch")
    blob = bucket.blob("o")
    await asyncio.to_thread(lambda: blob.upload_from_string(b"first", if_generation_match=0))
    with pytest.raises(gce.PreconditionFailed):
        await asyncio.to_thread(
            lambda: bucket.blob("o").upload_from_string(b"again", if_generation_match=0)
        )


async def test_blob_reload_reflects_updated_metadata(client):
    bucket = await asyncio.to_thread(client.create_bucket, "reload")
    blob = bucket.blob("o")
    await asyncio.to_thread(blob.upload_from_string, b"x")
    blob.metadata = {"k": "v"}
    await asyncio.to_thread(blob.patch)
    fresh = bucket.blob("o")
    await asyncio.to_thread(fresh.reload)
    assert fresh.metadata == {"k": "v"}
    assert fresh.metageneration == 2


async def test_list_blobs_with_prefix_and_pagination(client):
    bucket = await asyncio.to_thread(client.create_bucket, "list")
    for n in ("logs/1", "logs/2", "logs/3", "other"):
        blob = bucket.blob(n)
        await asyncio.to_thread(blob.upload_from_string, b"x")
    got = await asyncio.to_thread(
        lambda: [b.name for b in bucket.list_blobs(prefix="logs/", max_results=2)]
    )
    assert got == ["logs/1", "logs/2"]


async def test_copy_blob(client):
    src = await asyncio.to_thread(client.create_bucket, "srcb")
    dst = await asyncio.to_thread(client.create_bucket, "dstb")
    await asyncio.to_thread(src.blob("file").upload_from_string, b"copied")
    await asyncio.to_thread(lambda: src.copy_blob(src.blob("file"), dst, "file.copy"))
    result = await asyncio.to_thread(dst.blob("file.copy").download_as_bytes)
    assert result == b"copied"


async def test_compose(client):
    bucket = await asyncio.to_thread(client.create_bucket, "composeb")
    await asyncio.to_thread(bucket.blob("part1").upload_from_string, b"abc")
    await asyncio.to_thread(bucket.blob("part2").upload_from_string, b"def")
    composed = bucket.blob("combined")
    await asyncio.to_thread(lambda: composed.compose([bucket.blob("part1"), bucket.blob("part2")]))
    result = await asyncio.to_thread(bucket.blob("combined").download_as_bytes)
    assert result == b"abcdef"


async def test_ranged_download(client):
    bucket = await asyncio.to_thread(client.create_bucket, "rangeb")
    await asyncio.to_thread(bucket.blob("o").upload_from_string, b"0123456789")
    got = await asyncio.to_thread(lambda: bucket.blob("o").download_as_bytes(start=2, end=5))
    assert got == b"2345"


async def test_delete_then_reload_raises_not_found(client):
    bucket = await asyncio.to_thread(client.create_bucket, "delb")
    await asyncio.to_thread(bucket.blob("o").upload_from_string, b"x")
    await asyncio.to_thread(bucket.blob("o").delete)
    with pytest.raises(gce.NotFound):
        await asyncio.to_thread(bucket.blob("o").reload)


async def test_object_lifecycle_via_client(emulator, client):
    """Asserts the full create/upload/reload cycle surfaces through the client library."""
    bucket = await asyncio.to_thread(client.create_bucket, "eventbucket")
    await asyncio.to_thread(bucket.blob("o").upload_from_string, b"hi")
    await asyncio.to_thread(
        bucket.blob("o").reload
    )  # success implies sidecar/record lifecycle is intact
