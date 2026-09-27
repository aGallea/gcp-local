import base64
import hashlib
from collections.abc import AsyncIterator
from typing import Any, NoReturn

import google_crc32c
import grpc
from google.protobuf import empty_pb2
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.core.errors import GrpcError
from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.storage.v2 import storage_pb2, storage_pb2_grpc
from gcp_local.services.gcs.errors import GRPC_MAPPED_ERRORS, grpc_error_for
from gcp_local.services.gcs.events import publish_delete
from gcp_local.services.gcs.ids import GenerationCounter, decode_page_token, encode_page_token
from gcp_local.services.gcs.models import ObjectRecord
from gcp_local.services.gcs.operations import ComposeSource, compose_object, finalize_object
from gcp_local.services.gcs.preconditions import Preconditions, evaluate_preconditions
from gcp_local.services.gcs.storage import GcsStorage, ObjectNotFound

READ_CHUNK_BYTES = 2 * 1024 * 1024

_BUCKET_PREFIX = "projects/_/buckets/"
_UNSUPPORTED_LIST_FIELDS = (
    "versions",
    "soft_deleted",
    "match_glob",
    "filter",
    "lexicographic_start",
    "lexicographic_end",
)


def bucket_resource_name(bucket: str) -> str:
    return f"{_BUCKET_PREFIX}{bucket}"


def parse_bucket_name(resource: str) -> str:
    project, sep, bucket = resource.removeprefix("projects/").partition("/buckets/")
    if not resource.startswith("projects/") or not sep or not project or not bucket:
        raise GrpcError(
            grpc.StatusCode.INVALID_ARGUMENT,
            f"bucket must look like 'projects/_/buckets/<name>', got {resource!r}",
        )
    return bucket


def object_field(message: Message) -> str:
    # google-cloud-storage's proto-plus copy of these descriptors calls the field
    # `object_`, and whichever copy loads first owns the default descriptor pool.
    return "object" if "object" in message.DESCRIPTOR.fields_by_name else "object_"


def _object_name(request: Message) -> str:
    name: str = getattr(request, object_field(request))
    if not name:
        raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "object name is required")
    return name


def _optional(message: Message, field: str) -> int | None:
    if field not in message.DESCRIPTOR.fields_by_name or not message.HasField(field):
        return None
    return int(getattr(message, field))


def _preconditions(message: Message) -> Preconditions:
    return Preconditions(
        if_generation_match=_optional(message, "if_generation_match"),
        if_generation_not_match=_optional(message, "if_generation_not_match"),
        if_metageneration_match=_optional(message, "if_metageneration_match"),
        if_metageneration_not_match=_optional(message, "if_metageneration_not_match"),
    )


def _checksums(record: ObjectRecord) -> Any:
    # UI uploads store empty checksums; a present crc32c=0 would claim a checksum the data lacks.
    checksums = storage_pb2.ObjectChecksums()
    if record.crc32c:
        checksums.crc32c = int.from_bytes(base64.b64decode(record.crc32c), "big")
    if record.md5_hash:
        checksums.md5_hash = base64.b64decode(record.md5_hash)
    return checksums


def _timestamp(rfc3339: str) -> Timestamp:
    ts = Timestamp()
    ts.FromJsonString(rfc3339)
    return ts


def record_to_proto(record: ObjectRecord) -> Any:
    return storage_pb2.Object(
        name=record.name,
        bucket=bucket_resource_name(record.bucket),
        generation=record.generation,
        metageneration=record.metageneration,
        size=record.size,
        storage_class="STANDARD",
        content_type=record.content_type,
        content_encoding=record.content_encoding,
        content_language=record.content_language,
        content_disposition=record.content_disposition,
        cache_control=record.cache_control,
        checksums=_checksums(record),
        create_time=_timestamp(record.time_created),
        update_time=_timestamp(record.updated),
        metadata=dict(record.metadata),
    )


def _check_generation(record: ObjectRecord, generation: int) -> None:
    if generation and generation != record.generation:
        raise ObjectNotFound(f"{record.name}#{generation}")


def _read_window(size: int, read_offset: int, read_limit: int) -> tuple[int, int]:
    if read_limit < 0:
        raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "read_limit must not be negative")
    start = max(size + read_offset, 0) if read_offset < 0 else read_offset
    if start > size:
        raise GrpcError(
            grpc.StatusCode.OUT_OF_RANGE,
            f"read_offset {read_offset} is beyond the object size {size}",
        )
    end = size if read_limit == 0 else min(size, start + read_limit)
    return start, end


def _verify_crc32c(data: bytes, expected: int, what: str) -> None:
    actual = google_crc32c.value(data)
    if actual != expected:
        raise GrpcError(
            grpc.StatusCode.INVALID_ARGUMENT,
            f"{what} crc32c mismatch: expected {expected}, computed {actual}",
        )


class StorageServicer(storage_pb2_grpc.StorageServicer):
    def __init__(
        self,
        *,
        storage: GcsStorage,
        generations: GenerationCounter,
        state_hub: StateHub | None,
    ) -> None:
        self._storage = storage
        self._generations = generations
        self._state_hub = state_hub

    async def ListObjects(self, request: Any, context: grpc.aio.ServicerContext[Any, Any]) -> Any:
        try:
            bucket = parse_bucket_name(request.parent)
            for field in _UNSUPPORTED_LIST_FIELDS:
                if getattr(request, field):
                    raise GrpcError(
                        grpc.StatusCode.UNIMPLEMENTED, f"ListObjects {field} is not supported"
                    )
            if request.page_size < 0:
                raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "page_size must not be negative")
            page_size = request.page_size or None
            objects, prefixes = await self._storage.list_objects_with_prefixes(
                bucket,
                prefix=request.prefix,
                delimiter=request.delimiter or None,
                max_results=page_size,
                start_after=decode_page_token(request.page_token) if request.page_token else None,
            )
        except GRPC_MAPPED_ERRORS as exc:
            await _abort(context, exc)
        next_token = ""
        if page_size is not None and len(objects) == page_size:
            next_token = encode_page_token(objects[-1].name)
        return storage_pb2.ListObjectsResponse(
            objects=[record_to_proto(o) for o in objects],
            prefixes=prefixes,
            next_page_token=next_token,
        )

    async def GetObject(self, request: Any, context: grpc.aio.ServicerContext[Any, Any]) -> Any:
        try:
            record = await self._current(request)
        except GRPC_MAPPED_ERRORS as exc:
            await _abort(context, exc)
        return record_to_proto(record)

    async def ReadObject(
        self, request: Any, context: grpc.aio.ServicerContext[Any, Any]
    ) -> AsyncIterator[Any]:
        try:
            record = await self._current(request)
            data = await self._storage.get_object_bytes(record.bucket, record.name)
            start, end = _read_window(len(data), request.read_offset, request.read_limit)
        except GRPC_MAPPED_ERRORS as exc:
            await _abort(context, exc)

        first = storage_pb2.ReadObjectResponse(
            metadata=record_to_proto(record),
            object_checksums=_checksums(record),
        )
        if request.read_offset or request.read_limit:
            first.content_range.CopyFrom(
                storage_pb2.ContentRange(start=start, end=end, complete_length=len(data))
            )
        offset = start
        while True:
            chunk = data[offset : min(offset + READ_CHUNK_BYTES, end)]
            response = first if offset == start else storage_pb2.ReadObjectResponse()
            response.checksummed_data.CopyFrom(
                storage_pb2.ChecksummedData(content=chunk, crc32c=google_crc32c.value(chunk))
            )
            yield response
            offset += len(chunk)
            if offset >= end:
                return

    async def DeleteObject(self, request: Any, context: grpc.aio.ServicerContext[Any, Any]) -> Any:
        try:
            record = await self._current(request)
            await self._storage.delete_object(record.bucket, record.name)
        except GRPC_MAPPED_ERRORS as exc:
            await _abort(context, exc)
        await publish_delete(self._state_hub, record)
        return empty_pb2.Empty()

    async def ComposeObject(self, request: Any, context: grpc.aio.ServicerContext[Any, Any]) -> Any:
        try:
            if request.delete_source_objects:
                raise GrpcError(
                    grpc.StatusCode.UNIMPLEMENTED, "delete_source_objects is not supported"
                )
            destination = request.destination
            if not destination.name:
                raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "destination.name is required")
            record = await compose_object(
                storage=self._storage,
                generations=self._generations,
                state_hub=self._state_hub,
                bucket=parse_bucket_name(destination.bucket),
                name=destination.name,
                sources=[_compose_source(s) for s in request.source_objects],
                content_type=destination.content_type or "application/octet-stream",
                user_metadata=dict(destination.metadata),
                preconditions=_preconditions(request),
            )
        except GRPC_MAPPED_ERRORS as exc:
            await _abort(context, exc)
        return record_to_proto(record)

    async def WriteObject(
        self, request_iterator: AsyncIterator[Any], context: grpc.aio.ServicerContext[Any, Any]
    ) -> Any:
        try:
            spec, data = await _receive_write(request_iterator)
            resource = spec.resource
            if not resource.name:
                raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "resource.name is required")
            record = await finalize_object(
                storage=self._storage,
                generations=self._generations,
                state_hub=self._state_hub,
                bucket=parse_bucket_name(resource.bucket),
                name=resource.name,
                data=data,
                content_type=resource.content_type or "application/octet-stream",
                user_metadata=dict(resource.metadata),
                preconditions=_preconditions(spec),
            )
        except GRPC_MAPPED_ERRORS as exc:
            await _abort(context, exc)
        return storage_pb2.WriteObjectResponse(resource=record_to_proto(record))

    async def _current(self, request: Any) -> ObjectRecord:
        record = await self._storage.get_object(
            parse_bucket_name(request.bucket), _object_name(request)
        )
        _check_generation(record, request.generation)
        evaluate_preconditions(_preconditions(request), current=record)
        return record


def _compose_source(source: Any) -> ComposeSource:
    if not source.name:
        raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "source object missing name")
    pre = source.object_preconditions
    return ComposeSource(
        name=source.name,
        generation=source.generation or None,
        if_generation_match=_optional(pre, "if_generation_match"),
    )


async def _receive_write(requests: AsyncIterator[Any]) -> tuple[Any, bytes]:
    spec: Any = None
    buffer = bytearray()
    finished = False
    async for message in requests:
        if finished:
            raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "message received after finish_write")
        if spec is None:
            spec = _write_spec(message)
        elif message.WhichOneof("first_message") is not None:
            raise GrpcError(
                grpc.StatusCode.INVALID_ARGUMENT, "only the first message may carry the spec"
            )
        if message.write_offset != len(buffer):
            raise GrpcError(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"write_offset {message.write_offset} does not match the {len(buffer)} bytes "
                "persisted so far",
            )
        if message.HasField("checksummed_data"):
            chunk = message.checksummed_data
            if chunk.HasField("crc32c"):
                _verify_crc32c(chunk.content, chunk.crc32c, f"chunk at offset {len(buffer)}")
            buffer.extend(chunk.content)
        if message.finish_write:
            finished = True
            _verify_object_checksums(bytes(buffer), message.object_checksums)
    if spec is None:
        raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "empty WriteObject stream")
    if not finished:
        raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "stream ended without finish_write")
    if spec.HasField("object_size") and spec.object_size != len(buffer):
        raise GrpcError(
            grpc.StatusCode.INVALID_ARGUMENT,
            f"object_size {spec.object_size} does not match the {len(buffer)} bytes sent",
        )
    return spec, bytes(buffer)


def _write_spec(message: Any) -> Any:
    first = message.WhichOneof("first_message")
    if first == "upload_id":
        raise GrpcError(grpc.StatusCode.UNIMPLEMENTED, "resumable writes are not supported")
    if first != "write_object_spec":
        raise GrpcError(
            grpc.StatusCode.INVALID_ARGUMENT, "the first message must carry write_object_spec"
        )
    spec = message.write_object_spec
    if spec.appendable:
        raise GrpcError(grpc.StatusCode.UNIMPLEMENTED, "appendable objects are not supported")
    return spec


def _verify_object_checksums(data: bytes, checksums: Any) -> None:
    if checksums.HasField("crc32c"):
        _verify_crc32c(data, checksums.crc32c, "object")
    if checksums.md5_hash and checksums.md5_hash != hashlib.md5(data).digest():
        raise GrpcError(grpc.StatusCode.INVALID_ARGUMENT, "object md5_hash mismatch")


async def _abort(context: grpc.aio.ServicerContext[Any, Any], exc: Exception) -> NoReturn:
    err = grpc_error_for(exc)
    await context.abort(err.code, err.message)
