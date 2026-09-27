import base64
from collections.abc import AsyncIterator
from typing import Any

import google_crc32c
import grpc
import pytest

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.storage.v2 import storage_pb2
from gcp_local.services.gcs.events import EVENT_DELETE, EVENT_FINALIZE
from gcp_local.services.gcs.grpc_servicer import (
    READ_CHUNK_BYTES,
    StorageServicer,
    object_field,
    parse_bucket_name,
)
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.operations import finalize_object
from gcp_local.services.gcs.preconditions import Preconditions
from gcp_local.services.gcs.storage import InMemoryStorage

BUCKET = "bkt"
PARENT = f"projects/_/buckets/{BUCKET}"


class _Aborted(Exception):
    pass


class _FakeContext:
    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise _Aborted()


class _Harness:
    def __init__(self) -> None:
        self.storage = InMemoryStorage()
        self.generations = GenerationCounter()
        self.hub = StateHub()
        self.events: list[tuple[str, dict[str, Any]]] = []
        for topic in (EVENT_FINALIZE, EVENT_DELETE):
            self.hub.subscribe(topic, self._recorder(topic))
        self.servicer = StorageServicer(
            storage=self.storage, generations=self.generations, state_hub=self.hub
        )

    def _recorder(self, topic: str) -> Any:
        async def record(event: dict[str, Any]) -> None:
            self.events.append((topic, event))

        return record

    async def put(self, name: str, data: bytes, content_type: str = "text/plain") -> int:
        record = await finalize_object(
            storage=self.storage,
            generations=self.generations,
            state_hub=None,
            bucket=BUCKET,
            name=name,
            data=data,
            content_type=content_type,
            user_metadata={},
            preconditions=Preconditions(),
        )
        return record.generation


@pytest.fixture
async def h() -> _Harness:
    harness = _Harness()
    await harness.storage.create_bucket(BucketMeta(name=BUCKET, time_created="t"))
    return harness


def _obj_request(cls: Any, name: str, **fields: Any) -> Any:
    return cls(bucket=PARENT, **{object_field(cls()): name}, **fields)


async def _expect_abort(coro: Any) -> tuple[grpc.StatusCode, str]:
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await coro(ctx)
    assert ctx.aborted is not None
    return ctx.aborted


async def _read(h: _Harness, request: Any) -> list[Any]:
    return [r async for r in h.servicer.ReadObject(request, _FakeContext())]


async def _stream(*messages: Any) -> AsyncIterator[Any]:
    for m in messages:
        yield m


def _spec_message(name: str, **spec_fields: Any) -> Any:
    return storage_pb2.WriteObjectRequest(
        write_object_spec=storage_pb2.WriteObjectSpec(
            resource=storage_pb2.Object(name=name, bucket=PARENT, content_type="text/plain"),
            **spec_fields,
        )
    )


def _data_message(offset: int, chunk: bytes, crc32c: int | None = None) -> Any:
    return storage_pb2.WriteObjectRequest(
        write_offset=offset,
        checksummed_data=storage_pb2.ChecksummedData(
            content=chunk, crc32c=google_crc32c.value(chunk) if crc32c is None else crc32c
        ),
    )


def _finish_message(offset: int, data: bytes, crc32c: int | None = None) -> Any:
    return storage_pb2.WriteObjectRequest(
        write_offset=offset,
        finish_write=True,
        object_checksums=storage_pb2.ObjectChecksums(
            crc32c=google_crc32c.value(data) if crc32c is None else crc32c
        ),
    )


def test_parse_bucket_name_accepts_the_resource_form() -> None:
    assert parse_bucket_name("projects/_/buckets/my-bucket") == "my-bucket"


def test_parse_bucket_name_rejects_a_bare_bucket_name() -> None:
    from gcp_local.core.errors import GrpcError

    with pytest.raises(GrpcError) as exc:
        parse_bucket_name("my-bucket")
    assert exc.value.code == grpc.StatusCode.INVALID_ARGUMENT


async def test_list_objects_returns_objects_and_delimited_prefixes(h: _Harness) -> None:
    for name in ("a.txt", "dir/b.txt", "dir/sub/c.txt", "other/d.txt"):
        await h.put(name, b"x")
    resp = await h.servicer.ListObjects(
        storage_pb2.ListObjectsRequest(parent=PARENT, delimiter="/"), _FakeContext()
    )
    assert [o.name for o in resp.objects] == ["a.txt"]
    assert list(resp.prefixes) == ["dir/", "other/"]
    assert resp.objects[0].bucket == PARENT


async def test_list_objects_filters_by_prefix_and_treats_empty_delimiter_as_none(
    h: _Harness,
) -> None:
    for name in ("dir/b.txt", "dir/sub/c.txt", "else.txt"):
        await h.put(name, b"x")
    resp = await h.servicer.ListObjects(
        storage_pb2.ListObjectsRequest(parent=PARENT, prefix="dir/", delimiter=""),
        _FakeContext(),
    )
    assert [o.name for o in resp.objects] == ["dir/b.txt", "dir/sub/c.txt"]
    assert list(resp.prefixes) == []


async def test_list_objects_pages_with_page_size_and_token(h: _Harness) -> None:
    for name in ("a", "b", "c"):
        await h.put(name, b"x")
    first = await h.servicer.ListObjects(
        storage_pb2.ListObjectsRequest(parent=PARENT, page_size=2), _FakeContext()
    )
    assert [o.name for o in first.objects] == ["a", "b"]
    assert first.next_page_token
    second = await h.servicer.ListObjects(
        storage_pb2.ListObjectsRequest(
            parent=PARENT, page_size=2, page_token=first.next_page_token
        ),
        _FakeContext(),
    )
    assert [o.name for o in second.objects] == ["c"]
    assert second.next_page_token == ""


async def test_list_objects_rejects_versions(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.ListObjects(
            storage_pb2.ListObjectsRequest(parent=PARENT, versions=True), ctx
        )
    )
    assert code == grpc.StatusCode.UNIMPLEMENTED


async def test_list_objects_on_missing_bucket_is_not_found(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.ListObjects(
            storage_pb2.ListObjectsRequest(parent="projects/_/buckets/nope"), ctx
        )
    )
    assert code == grpc.StatusCode.NOT_FOUND


async def test_get_object_returns_metadata_with_checksums(h: _Harness) -> None:
    gen = await h.put("o.txt", b"hello")
    obj = await h.servicer.GetObject(
        _obj_request(storage_pb2.GetObjectRequest, "o.txt"), _FakeContext()
    )
    assert obj.name == "o.txt"
    assert obj.bucket == PARENT
    assert obj.generation == gen
    assert obj.size == 5
    assert obj.content_type == "text/plain"
    assert obj.checksums.crc32c == google_crc32c.value(b"hello")
    assert obj.create_time.seconds > 0


async def _put_without_checksums(h: _Harness, name: str, data: bytes) -> None:
    record = ObjectRecord(
        bucket=BUCKET,
        name=name,
        size=len(data),
        generation=h.generations.next(BUCKET),
        metageneration=1,
        md5_hash="",
        crc32c="",
        time_created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    await h.storage.put_object(record, data)


async def test_get_object_without_stored_checksums_omits_them(h: _Harness) -> None:
    await _put_without_checksums(h, "ui.txt", b"hello")
    obj = await h.servicer.GetObject(
        _obj_request(storage_pb2.GetObjectRequest, "ui.txt"), _FakeContext()
    )
    assert not obj.checksums.HasField("crc32c")
    assert obj.checksums.md5_hash == b""


async def test_read_object_without_stored_checksums_omits_object_checksums(h: _Harness) -> None:
    await _put_without_checksums(h, "ui.txt", b"hello")
    (first,) = await _read(h, _obj_request(storage_pb2.ReadObjectRequest, "ui.txt"))
    assert not first.object_checksums.HasField("crc32c")
    assert first.object_checksums.md5_hash == b""
    assert not first.metadata.checksums.HasField("crc32c")
    assert first.checksummed_data.content == b"hello"


async def test_get_object_missing_is_not_found(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.GetObject(_obj_request(storage_pb2.GetObjectRequest, "nope"), ctx)
    )
    assert code == grpc.StatusCode.NOT_FOUND


async def test_get_object_with_a_stale_generation_is_not_found(h: _Harness) -> None:
    gen = await h.put("o.txt", b"hello")
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.GetObject(
            _obj_request(storage_pb2.GetObjectRequest, "o.txt", generation=gen + 7), ctx
        )
    )
    assert code == grpc.StatusCode.NOT_FOUND


async def test_get_object_with_failed_generation_match_is_failed_precondition(
    h: _Harness,
) -> None:
    gen = await h.put("o.txt", b"hello")
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.GetObject(
            _obj_request(storage_pb2.GetObjectRequest, "o.txt", if_generation_match=gen + 1), ctx
        )
    )
    assert code == grpc.StatusCode.FAILED_PRECONDITION


async def test_read_object_streams_data_with_metadata_and_checksums_first(h: _Harness) -> None:
    await h.put("o.txt", b"hello world")
    responses = await _read(h, _obj_request(storage_pb2.ReadObjectRequest, "o.txt"))
    assert len(responses) == 1
    first = responses[0]
    assert first.metadata.name == "o.txt"
    assert first.object_checksums.crc32c == google_crc32c.value(b"hello world")
    assert first.checksummed_data.content == b"hello world"
    assert first.checksummed_data.crc32c == google_crc32c.value(b"hello world")
    assert not first.HasField("content_range")


async def test_read_object_splits_large_objects_into_chunks(h: _Harness) -> None:
    data = bytes(range(256)) * (READ_CHUNK_BYTES // 256 + 10)
    await h.put("big", data)
    responses = await _read(h, _obj_request(storage_pb2.ReadObjectRequest, "big"))
    assert len(responses) == 2
    assert b"".join(r.checksummed_data.content for r in responses) == data
    assert not responses[1].HasField("metadata")
    for r in responses:
        chunk = r.checksummed_data
        assert chunk.crc32c == google_crc32c.value(chunk.content)


async def test_read_object_honors_read_offset_and_read_limit(h: _Harness) -> None:
    await h.put("o.txt", b"0123456789")
    responses = await _read(
        h, _obj_request(storage_pb2.ReadObjectRequest, "o.txt", read_offset=2, read_limit=3)
    )
    assert b"".join(r.checksummed_data.content for r in responses) == b"234"
    rng = responses[0].content_range
    assert (rng.start, rng.end, rng.complete_length) == (2, 5, 10)


async def test_read_object_negative_offset_counts_back_from_the_end(h: _Harness) -> None:
    await h.put("o.txt", b"0123456789")
    responses = await _read(h, _obj_request(storage_pb2.ReadObjectRequest, "o.txt", read_offset=-4))
    assert b"".join(r.checksummed_data.content for r in responses) == b"6789"


async def test_read_object_of_an_empty_object_still_sends_metadata(h: _Harness) -> None:
    await h.put("empty", b"")
    responses = await _read(h, _obj_request(storage_pb2.ReadObjectRequest, "empty"))
    assert len(responses) == 1
    assert responses[0].metadata.name == "empty"
    assert responses[0].checksummed_data.content == b""


async def test_read_object_offset_past_the_end_is_out_of_range(h: _Harness) -> None:
    await h.put("o.txt", b"abc")

    async def call(ctx: Any) -> None:
        req = _obj_request(storage_pb2.ReadObjectRequest, "o.txt", read_offset=10)
        async for _ in h.servicer.ReadObject(req, ctx):
            pass

    code, _ = await _expect_abort(call)
    assert code == grpc.StatusCode.OUT_OF_RANGE


async def test_read_object_negative_limit_is_invalid(h: _Harness) -> None:
    await h.put("o.txt", b"abc")

    async def call(ctx: Any) -> None:
        req = _obj_request(storage_pb2.ReadObjectRequest, "o.txt", read_limit=-1)
        async for _ in h.servicer.ReadObject(req, ctx):
            pass

    code, _ = await _expect_abort(call)
    assert code == grpc.StatusCode.INVALID_ARGUMENT


async def test_delete_object_removes_it_and_publishes_delete(h: _Harness) -> None:
    await h.put("o.txt", b"x")
    await h.servicer.DeleteObject(
        _obj_request(storage_pb2.DeleteObjectRequest, "o.txt"), _FakeContext()
    )
    assert await h.storage.list_objects(BUCKET) == []
    assert [t for t, _ in h.events] == [EVENT_DELETE]


async def test_delete_object_missing_is_not_found(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.DeleteObject(
            _obj_request(storage_pb2.DeleteObjectRequest, "nope"), ctx
        )
    )
    assert code == grpc.StatusCode.NOT_FOUND


async def test_compose_object_concatenates_sources_and_publishes_finalize(h: _Harness) -> None:
    await h.put("p1", b"hello ")
    await h.put("p2", b"world")
    obj = await h.servicer.ComposeObject(
        storage_pb2.ComposeObjectRequest(
            destination=storage_pb2.Object(name="whole", bucket=PARENT, content_type="text/x"),
            source_objects=[
                storage_pb2.ComposeObjectRequest.SourceObject(name="p1"),
                storage_pb2.ComposeObjectRequest.SourceObject(name="p2"),
            ],
        ),
        _FakeContext(),
    )
    assert obj.size == 11
    assert obj.content_type == "text/x"
    assert await h.storage.get_object_bytes(BUCKET, "whole") == b"hello world"
    assert [t for t, _ in h.events] == [EVENT_FINALIZE]


async def test_compose_object_with_failed_destination_generation_match_is_failed_precondition(
    h: _Harness,
) -> None:
    await h.put("p1", b"a")
    gen = await h.put("whole", b"old")
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.ComposeObject(
            storage_pb2.ComposeObjectRequest(
                destination=storage_pb2.Object(name="whole", bucket=PARENT),
                source_objects=[storage_pb2.ComposeObjectRequest.SourceObject(name="p1")],
                if_generation_match=gen + 1,
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.FAILED_PRECONDITION
    assert await h.storage.get_object_bytes(BUCKET, "whole") == b"old"


async def test_compose_object_with_failed_source_precondition_is_failed_precondition(
    h: _Harness,
) -> None:
    gen = await h.put("p1", b"a")
    source = storage_pb2.ComposeObjectRequest.SourceObject(
        name="p1",
        object_preconditions=storage_pb2.ComposeObjectRequest.SourceObject.ObjectPreconditions(
            if_generation_match=gen + 1
        ),
    )
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.ComposeObject(
            storage_pb2.ComposeObjectRequest(
                destination=storage_pb2.Object(name="whole", bucket=PARENT),
                source_objects=[source],
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.FAILED_PRECONDITION


async def test_compose_object_with_a_missing_source_is_not_found(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.ComposeObject(
            storage_pb2.ComposeObjectRequest(
                destination=storage_pb2.Object(name="whole", bucket=PARENT),
                source_objects=[storage_pb2.ComposeObjectRequest.SourceObject(name="nope")],
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.NOT_FOUND


async def test_compose_object_without_sources_is_invalid(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.ComposeObject(
            storage_pb2.ComposeObjectRequest(
                destination=storage_pb2.Object(name="whole", bucket=PARENT)
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.INVALID_ARGUMENT


async def test_write_object_assembles_chunks_and_returns_the_resource(h: _Harness) -> None:
    resp = await h.servicer.WriteObject(
        _stream(
            _spec_message("w.txt"),
            _data_message(0, b"hello "),
            _data_message(6, b"world"),
            _finish_message(11, b"hello world"),
        ),
        _FakeContext(),
    )
    assert resp.resource.name == "w.txt"
    assert resp.resource.bucket == PARENT
    assert resp.resource.size == 11
    assert resp.resource.content_type == "text/plain"
    assert resp.resource.checksums.crc32c == google_crc32c.value(b"hello world")
    assert await h.storage.get_object_bytes(BUCKET, "w.txt") == b"hello world"
    assert [t for t, _ in h.events] == [EVENT_FINALIZE]


async def test_write_object_of_zero_bytes_creates_an_empty_object(h: _Harness) -> None:
    resp = await h.servicer.WriteObject(
        _stream(_spec_message("empty"), _finish_message(0, b"")), _FakeContext()
    )
    assert resp.resource.size == 0
    assert await h.storage.get_object_bytes(BUCKET, "empty") == b""


async def test_write_object_with_if_generation_match_zero_refuses_to_overwrite(
    h: _Harness,
) -> None:
    await h.put("w.txt", b"old")
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt", if_generation_match=0),
                _data_message(0, b"new"),
                _finish_message(3, b"new"),
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.FAILED_PRECONDITION
    assert await h.storage.get_object_bytes(BUCKET, "w.txt") == b"old"


async def test_write_object_with_matching_generation_overwrites(h: _Harness) -> None:
    gen = await h.put("w.txt", b"old")
    resp = await h.servicer.WriteObject(
        _stream(
            _spec_message("w.txt", if_generation_match=gen),
            _data_message(0, b"new"),
            _finish_message(3, b"new"),
        ),
        _FakeContext(),
    )
    assert resp.resource.generation > gen


async def test_write_object_overwrite_gets_a_new_generation_and_creation_time(
    h: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamps = iter(["2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z"])
    monkeypatch.setattr("gcp_local.services.gcs.operations.rfc3339_now", lambda: next(stamps))
    written = []
    for data in (b"v1", b"v2"):
        resp = await h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt"),
                _data_message(0, data),
                _finish_message(len(data), data),
            ),
            _FakeContext(),
        )
        written.append(resp.resource)
    first, second = written
    assert first.generation != second.generation
    assert second.create_time.seconds > first.create_time.seconds
    assert second.create_time == second.update_time


async def test_write_object_with_if_generation_not_match_on_current_fails(h: _Harness) -> None:
    gen = await h.put("w.txt", b"old")
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt", if_generation_not_match=gen),
                _finish_message(0, b""),
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.FAILED_PRECONDITION


async def test_write_object_with_if_metageneration_match_on_missing_object_fails(
    h: _Harness,
) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt", if_metageneration_match=1),
                _finish_message(0, b""),
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.FAILED_PRECONDITION


async def test_write_object_with_a_bad_chunk_crc32c_is_invalid(h: _Harness) -> None:
    code, details = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt"),
                _data_message(0, b"hello", crc32c=1234),
                _finish_message(5, b"hello"),
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.INVALID_ARGUMENT
    assert "crc32c" in details
    assert await h.storage.list_objects(BUCKET) == []


async def test_write_object_with_a_bad_object_crc32c_is_invalid(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt"),
                _data_message(0, b"hello"),
                _finish_message(5, b"hello", crc32c=google_crc32c.value(b"hellp")),
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.INVALID_ARGUMENT
    assert await h.storage.list_objects(BUCKET) == []


async def test_write_object_with_a_bad_md5_is_invalid(h: _Harness) -> None:
    finish = storage_pb2.WriteObjectRequest(
        write_offset=5,
        finish_write=True,
        object_checksums=storage_pb2.ObjectChecksums(md5_hash=base64.b64decode("AAAA")),
    )
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(_spec_message("w.txt"), _data_message(0, b"hello"), finish), ctx
        )
    )
    assert code == grpc.StatusCode.INVALID_ARGUMENT


async def test_write_object_with_a_gap_in_write_offset_is_invalid(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt"),
                _data_message(0, b"hello"),
                _data_message(9, b"world"),
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.INVALID_ARGUMENT


async def test_write_object_without_finish_write_is_invalid(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(_spec_message("w.txt"), _data_message(0, b"hello")), ctx
        )
    )
    assert code == grpc.StatusCode.INVALID_ARGUMENT
    assert await h.storage.list_objects(BUCKET) == []


async def test_write_object_with_mismatched_object_size_is_invalid(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(
                _spec_message("w.txt", object_size=99),
                _data_message(0, b"hello"),
                _finish_message(5, b"hello"),
            ),
            ctx,
        )
    )
    assert code == grpc.StatusCode.INVALID_ARGUMENT


async def test_write_object_starting_with_an_upload_id_is_unimplemented(h: _Harness) -> None:
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(
            _stream(storage_pb2.WriteObjectRequest(upload_id="abc")), ctx
        )
    )
    assert code == grpc.StatusCode.UNIMPLEMENTED


async def test_write_object_to_a_missing_bucket_is_not_found(h: _Harness) -> None:
    spec = storage_pb2.WriteObjectRequest(
        write_object_spec=storage_pb2.WriteObjectSpec(
            resource=storage_pb2.Object(name="w", bucket="projects/_/buckets/nope")
        )
    )
    code, _ = await _expect_abort(
        lambda ctx: h.servicer.WriteObject(_stream(spec, _finish_message(0, b"")), ctx)
    )
    assert code == grpc.StatusCode.NOT_FOUND
