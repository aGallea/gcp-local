import contextlib
import json
from email.parser import BytesParser
from email.policy import compat32
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_finalize
from gcp_local.services.gcs.ids import (
    GenerationCounter,
    compute_crc32c_b64,
    compute_md5_b64,
    new_session_id,
    rfc3339_now,
)
from gcp_local.services.gcs.models import ObjectRecord, UploadSession
from gcp_local.services.gcs.preconditions import (
    PreconditionFailed,
    Preconditions,
    evaluate_preconditions,
)
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectCollision,
    ObjectNotFound,
    SessionNotFound,
)


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, Any], bytes, str]:
    """Return (metadata_dict, object_bytes, object_content_type)."""
    header = f"Content-Type: {content_type}\r\n\r\n".encode()
    msg = BytesParser(policy=compat32).parsebytes(header + body)
    parts = list(msg.walk())
    # parts[0] is the container; real parts are [1:]
    meta_part = parts[1]
    obj_part = parts[2]
    raw_meta = meta_part.get_payload(decode=True)
    assert isinstance(raw_meta, bytes)
    metadata: dict[str, Any] = json.loads(raw_meta.decode("utf-8"))
    obj_ct = obj_part.get_content_type() or "application/octet-stream"
    raw_obj = obj_part.get_payload(decode=True)
    assert isinstance(raw_obj, bytes)
    return metadata, raw_obj, obj_ct


async def _finalize_object(
    *,
    storage: GcsStorage,
    generations: GenerationCounter,
    state_hub: StateHub | None,
    bucket: str,
    name: str,
    data: bytes,
    content_type: str,
    user_metadata: dict[str, str],
    preconditions: Preconditions,
) -> ObjectRecord:
    try:
        current = await storage.get_object(bucket, name)
    except ObjectNotFound:
        current = None
    evaluate_preconditions(preconditions, current=current)

    now = rfc3339_now()
    record = ObjectRecord(
        bucket=bucket,
        name=name,
        size=len(data),
        generation=generations.next(bucket),
        metageneration=1,
        content_type=content_type,
        md5_hash=compute_md5_b64(data),
        crc32c=compute_crc32c_b64(data),
        time_created=now if current is None else current.time_created,
        updated=now,
        metadata=dict(user_metadata),
    )
    await storage.put_object(record, data)
    await publish_finalize(state_hub, record)
    return record


def register_upload_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
    generations: GenerationCounter,
) -> None:
    @router.post("/upload/storage/v1/b/{bucket}/o")
    async def upload(
        bucket: str,
        request: Request,
        uploadType: str = Query(..., alias="uploadType"),
        name: str | None = Query(default=None),
        ifGenerationMatch: int | None = Query(default=None, alias="ifGenerationMatch"),
        ifGenerationNotMatch: int | None = Query(default=None, alias="ifGenerationNotMatch"),
        ifMetagenerationMatch: int | None = Query(default=None, alias="ifMetagenerationMatch"),
        ifMetagenerationNotMatch: int | None = Query(
            default=None, alias="ifMetagenerationNotMatch"
        ),
    ) -> JSONResponse:
        pre = Preconditions(
            if_generation_match=ifGenerationMatch,
            if_generation_not_match=ifGenerationNotMatch,
            if_metageneration_match=ifMetagenerationMatch,
            if_metageneration_not_match=ifMetagenerationNotMatch,
        )

        try:
            if uploadType == "media":
                if not name:
                    return error_response(400, "invalid", "missing object name")
                data = await request.body()
                ct = request.headers.get("content-type", "application/octet-stream")
                record = await _finalize_object(
                    storage=storage,
                    generations=generations,
                    state_hub=state_hub,
                    bucket=bucket,
                    name=name,
                    data=data,
                    content_type=ct,
                    user_metadata={},
                    preconditions=pre,
                )
                return JSONResponse(record.model_dump(by_alias=True))

            if uploadType == "multipart":
                body = await request.body()
                ct = request.headers.get("content-type", "")
                try:
                    metadata, obj_bytes, obj_ct = _parse_multipart(body, ct)
                except Exception as e:
                    return error_response(400, "invalid", f"multipart parse error: {e}")
                obj_name = metadata.get("name")
                if not obj_name or not isinstance(obj_name, str):
                    return error_response(
                        400, "invalid", "missing object name in multipart metadata"
                    )
                raw_ct = metadata.get("contentType", obj_ct)
                obj_content_type = str(raw_ct) if raw_ct else obj_ct
                raw_user_meta = metadata.get("metadata", {})
                user_meta: dict[str, str] = (
                    {str(k): str(v) for k, v in raw_user_meta.items()}
                    if isinstance(raw_user_meta, dict)
                    else {}
                )
                record = await _finalize_object(
                    storage=storage,
                    generations=generations,
                    state_hub=state_hub,
                    bucket=bucket,
                    name=obj_name,
                    data=obj_bytes,
                    content_type=obj_content_type,
                    user_metadata=user_meta,
                    preconditions=pre,
                )
                return JSONResponse(record.model_dump(by_alias=True))

            if uploadType == "resumable":
                ct = request.headers.get(
                    "x-upload-content-type",
                    request.headers.get("content-type", "application/octet-stream"),
                )
                body_bytes = await request.body()
                user_metadata: dict[str, str] = {}
                init_content_type = ct
                init_name = name
                if body_bytes:
                    try:
                        init_body = json.loads(body_bytes)
                        init_name = init_body.get("name", name)
                        init_content_type = init_body.get("contentType", ct)
                        user_metadata = init_body.get("metadata", {})
                    except json.JSONDecodeError:
                        pass
                if not init_name:
                    return error_response(400, "invalid", "missing object name")
                session_id = new_session_id()
                total = request.headers.get("x-upload-content-length")
                total_size = int(total) if total else None
                now = rfc3339_now()
                sess = UploadSession(
                    session_id=session_id,
                    bucket=bucket,
                    object_name=init_name,
                    total_size=total_size,
                    bytes_received=0,
                    content_type=init_content_type,
                    user_metadata=user_metadata,
                    created_at=now,
                    last_chunk_at=now,
                )
                await storage.put_session(sess)
                base_url = str(request.base_url).rstrip("/")
                location = f"{base_url}/upload/storage/v1/b/{bucket}/o?upload_id={session_id}"
                return JSONResponse(
                    {"uploadId": session_id},
                    status_code=200,
                    headers={"Location": location},
                )

            return error_response(400, "invalid", f"unsupported uploadType: {uploadType}")
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except PreconditionFailed as e:
            return error_response(412, "conditionNotMet", str(e))
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))

    @router.put("/upload/storage/v1/b/{bucket}/o")
    async def resumable_chunk(
        bucket: str,
        request: Request,
        upload_id: str = Query(..., alias="upload_id"),
    ) -> Response:
        try:
            sess = await storage.get_session(upload_id)
        except SessionNotFound:
            return error_response(404, "notFound", f"upload session {upload_id!r} not found")

        cr = request.headers.get("content-range", "")
        # Status query: "bytes */*"
        if cr == "bytes */*":
            headers: dict[str, str] = {}
            if sess.bytes_received > 0:
                end = sess.bytes_received - 1
                headers["Range"] = f"bytes=0-{end}"
            return Response(status_code=308, headers=headers)

        # Chunk upload: "bytes N-M/total" or "bytes N-M/*"
        if not cr.startswith("bytes "):
            return error_response(400, "invalid", "missing or malformed Content-Range header")
        spec = cr[len("bytes ") :]
        range_part, _, total_part = spec.partition("/")
        try:
            start, end = (int(x) for x in range_part.split("-"))
        except ValueError:
            return error_response(400, "invalid", f"bad Content-Range: {cr}")
        if start != sess.bytes_received:
            return error_response(
                400,
                "invalid",
                f"chunk starts at {start}, expected {sess.bytes_received}",
            )

        chunk = await request.body()
        if len(chunk) != (end - start + 1):
            return error_response(
                400,
                "invalid",
                f"chunk length {len(chunk)} does not match range {range_part}",
            )

        await storage.append_to_session(upload_id, chunk)
        sess = await storage.get_session(upload_id)

        total_known: int | None
        if total_part == "*":
            total_known = None
        else:
            try:
                total_known = int(total_part)
            except ValueError:
                return error_response(400, "invalid", f"bad total: {total_part}")

        is_final = total_known is not None and sess.bytes_received >= total_known
        if not is_final:
            return Response(
                status_code=308,
                headers={"Range": f"bytes=0-{sess.bytes_received - 1}"},
            )

        data = await storage.get_session_bytes(upload_id)
        try:
            record = await _finalize_object(
                storage=storage,
                generations=generations,
                state_hub=state_hub,
                bucket=sess.bucket,
                name=sess.object_name,
                data=data,
                content_type=sess.content_type,
                user_metadata=dict(sess.user_metadata),
                preconditions=Preconditions(),
            )
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {sess.bucket!r} not found")
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))
        finally:
            with contextlib.suppress(SessionNotFound):
                await storage.delete_session(upload_id)

        return JSONResponse(record.model_dump(by_alias=True))
