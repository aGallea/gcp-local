import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Any

import google_crc32c
import pytest
import pytest_asyncio
from google.api_core import exceptions as gce
from google.api_core import gapic_v1
from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from google.cloud._storage_v2.types import storage as pb
from google.cloud.storage.asyncio.async_grpc_client import AsyncGrpcClient


@pytest.fixture
def rest(emulator, monkeypatch):
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", f"http://127.0.0.1:{emulator['gcs_port']}")
    return storage.Client(
        project="test-project",
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": f"http://127.0.0.1:{emulator['gcs_port']}"},
    )


@pytest_asyncio.fixture
async def grpc_client(emulator) -> AsyncIterator[Any]:
    client = AsyncGrpcClient(
        credentials=AnonymousCredentials(),
        client_options=ClientOptions(api_endpoint=f"127.0.0.1:{emulator['gcs_grpc_port']}"),
    ).grpc_client
    yield client
    await client.transport.close()


@pytest_asyncio.fixture
async def bucket(rest) -> str:
    await asyncio.to_thread(rest.create_bucket, "grpc-bkt")
    return "projects/_/buckets/grpc-bkt"


async def _write(
    client: Any,
    bucket: str,
    name: str,
    chunks: Iterable[bytes],
    *,
    if_generation_match: int | None = None,
    object_crc32c: int | None = None,
    chunk_crc32c: int | None = None,
) -> Any:
    spec = pb.WriteObjectSpec(resource=pb.Object(name=name, bucket=bucket))
    if if_generation_match is not None:
        spec.if_generation_match = if_generation_match

    async def requests() -> AsyncIterator[Any]:
        whole = google_crc32c.Checksum()
        offset = 0
        yield pb.WriteObjectRequest(write_object_spec=spec)
        for chunk in chunks:
            whole.update(chunk)
            crc = google_crc32c.value(chunk) if chunk_crc32c is None else chunk_crc32c
            yield pb.WriteObjectRequest(
                write_offset=offset,
                checksummed_data=pb.ChecksummedData(content=chunk, crc32c=crc),
            )
            offset += len(chunk)
        crc = int.from_bytes(whole.digest(), "big") if object_crc32c is None else object_crc32c
        yield pb.WriteObjectRequest(
            write_offset=offset,
            finish_write=True,
            object_checksums=pb.ObjectChecksums(crc32c=crc),
        )

    routing = gapic_v1.routing_header.to_grpc_metadata({"bucket": bucket})
    call = await client.write_object(requests=requests(), metadata=(routing,))
    response = await call
    return response.resource


async def _read(client: Any, bucket: str, name: str, **fields: Any) -> tuple[bytes, list[Any]]:
    stream = await client.read_object(
        request={"bucket": bucket, "object_": name, "generation": 0, **fields}
    )
    responses = [r async for r in stream]
    return b"".join(r.checksummed_data.content for r in responses), responses


async def test_write_object_then_read_object_round_trips_bytes_and_metadata(grpc_client, bucket):
    data = b"a" * (3 * 1024 * 1024) + b"tail"
    chunks = [data[i : i + 2 * 1024 * 1024] for i in range(0, len(data), 2 * 1024 * 1024)]
    written = await _write(grpc_client, bucket, "dir/obj.bin", chunks)
    assert written.name == "dir/obj.bin"
    assert written.bucket == bucket
    assert written.size == len(data)
    assert written.checksums.crc32c == google_crc32c.value(data)

    got, responses = await _read(grpc_client, bucket, "dir/obj.bin")
    assert got == data
    assert responses[0].metadata.name == "dir/obj.bin"
    assert responses[0].metadata.generation == written.generation
    assert responses[0].object_checksums.crc32c == google_crc32c.value(data)


async def test_read_object_with_offset_and_limit_returns_the_range(grpc_client, bucket):
    await _write(grpc_client, bucket, "r.txt", [b"0123456789"])
    got, responses = await _read(grpc_client, bucket, "r.txt", read_offset=3, read_limit=4)
    assert got == b"3456"
    assert responses[0].content_range.start == 3
    assert responses[0].content_range.end == 7
    assert responses[0].content_range.complete_length == 10


async def test_get_object_returns_the_object_and_404s_when_missing(grpc_client, bucket):
    written = await _write(grpc_client, bucket, "g.txt", [b"hi"])
    obj = await grpc_client.get_object(request={"bucket": bucket, "object_": "g.txt"})
    assert obj.name == "g.txt"
    assert obj.generation == written.generation
    assert obj.size == 2
    with pytest.raises(gce.NotFound):
        await grpc_client.get_object(request={"bucket": bucket, "object_": "missing"})


async def test_list_objects_pages_and_splits_prefixes(grpc_client, bucket):
    for name in ("a.txt", "b.txt", "c.txt", "logs/1", "logs/2"):
        await _write(grpc_client, bucket, name, [b"x"])

    pager = await grpc_client.list_objects(
        request={"parent": bucket, "prefix": "", "delimiter": "/", "page_size": 2}
    )
    names: list[str] = []
    prefixes: list[str] = []
    pages = 0
    async for page in pager.pages:
        pages += 1
        names.extend(o.name for o in page.objects)
        prefixes.extend(page.prefixes)
    assert names == ["a.txt", "b.txt", "c.txt"]
    assert set(prefixes) == {"logs/"}
    assert pages >= 2

    pager = await grpc_client.list_objects(
        request={"parent": bucket, "prefix": "logs/", "delimiter": ""}
    )
    all_names = [o.name async for o in pager]
    assert all_names == ["logs/1", "logs/2"]


async def test_delete_object_removes_it(grpc_client, bucket):
    await _write(grpc_client, bucket, "d.txt", [b"x"])
    await grpc_client.delete_object(request={"bucket": bucket, "object_": "d.txt"})
    with pytest.raises(gce.NotFound):
        await grpc_client.get_object(request={"bucket": bucket, "object_": "d.txt"})
    with pytest.raises(gce.NotFound):
        await grpc_client.delete_object(request={"bucket": bucket, "object_": "d.txt"})


async def test_compose_object_concatenates_and_honors_if_generation_match(grpc_client, bucket):
    await _write(grpc_client, bucket, "p1", [b"hello "])
    await _write(grpc_client, bucket, "p2", [b"world"])
    request = pb.ComposeObjectRequest(
        destination=pb.Object(name="whole", bucket=bucket),
        source_objects=[pb.ComposeObjectRequest.SourceObject(name=s) for s in ("p1", "p2")],
    )
    request.if_generation_match = 0
    composed = await grpc_client.compose_object(request=request)
    assert composed.size == 11
    got, _ = await _read(grpc_client, bucket, "whole")
    assert got == b"hello world"

    with pytest.raises(gce.FailedPrecondition):
        await grpc_client.compose_object(request=request)


async def test_write_object_with_stale_if_generation_match_fails_precondition(grpc_client, bucket):
    first = await _write(grpc_client, bucket, "w.txt", [b"v1"], if_generation_match=0)
    with pytest.raises(gce.FailedPrecondition):
        await _write(grpc_client, bucket, "w.txt", [b"v2"], if_generation_match=0)
    second = await _write(
        grpc_client, bucket, "w.txt", [b"v2"], if_generation_match=first.generation
    )
    assert second.generation > first.generation


async def test_write_object_with_bad_checksums_is_rejected_and_stores_nothing(grpc_client, bucket):
    with pytest.raises(gce.InvalidArgument):
        await _write(grpc_client, bucket, "bad", [b"payload"], chunk_crc32c=1)
    with pytest.raises(gce.InvalidArgument):
        await _write(grpc_client, bucket, "bad", [b"payload"], object_crc32c=1)
    with pytest.raises(gce.NotFound):
        await grpc_client.get_object(request={"bucket": bucket, "object_": "bad"})


async def test_rest_write_is_readable_over_grpc_at_the_same_generation(rest, grpc_client, bucket):
    blob = rest.bucket("grpc-bkt").blob("from-rest.txt")
    await asyncio.to_thread(blob.upload_from_string, b"rest bytes", content_type="text/plain")

    got, responses = await _read(grpc_client, bucket, "from-rest.txt")
    assert got == b"rest bytes"
    assert responses[0].metadata.generation == blob.generation
    assert responses[0].metadata.content_type == "text/plain"


async def test_grpc_write_is_readable_over_rest_at_the_same_generation(rest, grpc_client, bucket):
    written = await _write(grpc_client, bucket, "from-grpc.txt", [b"grpc bytes"])

    blob = await asyncio.to_thread(rest.bucket("grpc-bkt").get_blob, "from-grpc.txt")
    assert blob.generation == written.generation
    assert await asyncio.to_thread(blob.download_as_bytes) == b"grpc bytes"

    rest_blob = rest.bucket("grpc-bkt").blob("after.txt")
    await asyncio.to_thread(rest_blob.upload_from_string, b"later")
    assert rest_blob.generation > written.generation
