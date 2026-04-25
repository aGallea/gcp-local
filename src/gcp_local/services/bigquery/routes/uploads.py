"""Upload handlers: /upload/bigquery/v2/projects/{p}/jobs (spec §3).

Two upload styles share the endpoint, dispatched on uploadType:

- multipart: single POST with a multipart/related body (metadata JSON +
  data payload). Runs the load synchronously and returns the Job.
- resumable: init POST returns a session URL; PUT chunks accumulate into
  an in-memory buffer; the final PUT runs the load.
"""

import email
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, Header, Request, Response

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.engine.resumable import (
    OutOfOrderChunk,
    ResumableSessionNotFound,
    ResumableSessionStore,
)
from gcp_local.services.bigquery.errors import bigquery_error_response, make_error_response
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_project_id,
)
from gcp_local.services.bigquery.routes.jobs import job_to_api

_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)


class MultipartParseError(ValueError):
    pass


def parse_multipart_related(body: bytes, content_type: str) -> tuple[dict[str, Any], bytes]:
    """Return (metadata_json, data_bytes) from a multipart/related body."""
    if "multipart/related" not in content_type.lower():
        raise MultipartParseError(
            f"expected multipart/related, got {content_type!r}"
        )
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    # Use the compat (non-policy) API — email.policy.default breaks binary payloads.
    msg = email.message_from_bytes(raw)
    # walk() yields the outer envelope first, then each part.
    parts = [p for p in msg.walk() if not p.get_content_maintype() == "multipart"]
    if len(parts) < 2:
        raise MultipartParseError(
            f"multipart body must have at least 2 parts, got {len(parts)}"
        )
    metadata_part = parts[0]
    data_part = parts[1]
    md_ct = metadata_part.get_content_type()
    if md_ct != "application/json":
        raise MultipartParseError(
            f"first part must be application/json, got {md_ct!r}"
        )
    try:
        metadata = json.loads(metadata_part.get_payload(decode=True).decode("utf-8"))
    except json.JSONDecodeError as e:
        raise MultipartParseError(f"metadata is not valid JSON: {e}") from e
    data = data_part.get_payload(decode=True) or b""
    return metadata, data


def build_router(
    runner: JobRunner,
    load_runner: LoadRunner,
    resumables: ResumableSessionStore,
) -> APIRouter:
    router = APIRouter(prefix="/upload/bigquery/v2/projects")

    @router.post("/{project}/jobs")
    async def upload_job(
        project: str,
        request: Request,
        uploadType: str = "",  # noqa: N803
        content_type: str = Header(default="application/octet-stream"),
    ) -> Any:
        try:
            validate_project_id(project)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

        body = await request.body()
        if uploadType == "multipart":
            return await _handle_multipart(
                project=project,
                body=body,
                content_type=content_type,
                load_runner=load_runner,
                runner=runner,
            )
        if uploadType == "resumable":
            return _handle_resumable_init(
                project=project,
                body=body,
                request=request,
                resumables=resumables,
            )
        return make_error_response(400, f"Unsupported uploadType: {uploadType!r}")

    @router.put("/{project}/jobs")
    async def upload_chunk(
        project: str,
        request: Request,
        upload_id: str = "",  # noqa: N803
        content_range: str = Header(default=""),
    ) -> Any:
        try:
            validate_project_id(project)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()
        return await _handle_resumable_put(
            project=project,
            upload_id=upload_id,
            body=await request.body(),
            content_range=content_range,
            resumables=resumables,
            load_runner=load_runner,
            runner=runner,
        )

    @router.delete("/{project}/jobs")
    async def cancel_resumable(
        project: str,
        upload_id: str = "",  # noqa: N803
    ) -> Any:
        try:
            validate_project_id(project)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()
        resumables.drop(upload_id)
        return Response(status_code=200, content=b"")

    return router


async def _handle_multipart(
    *,
    project: str,
    body: bytes,
    content_type: str,
    load_runner: LoadRunner,
    runner: JobRunner,
) -> Any:
    try:
        metadata, data = parse_multipart_related(body, content_type)
    except MultipartParseError as e:
        return make_error_response(400, str(e))
    return await _run_load_and_persist(
        project=project,
        metadata=metadata,
        data=data,
        load_runner=load_runner,
        runner=runner,
    )


async def _run_load_and_persist(
    *,
    project: str,
    metadata: dict[str, Any],
    data: bytes,
    load_runner: LoadRunner,
    runner: JobRunner,
) -> Any:
    job_ref = metadata.get("jobReference") or {}
    job_id = job_ref.get("jobId") or _gen_job_id()
    load_config = ((metadata.get("configuration") or {}).get("load")) or {}
    rec = await load_runner.run_load(
        project=project,
        job_id=job_id,
        load_config=load_config,
        data=data,
    )
    runner.register_external(rec)
    return job_to_api(rec)


def _handle_resumable_init(
    *,
    project: str,
    body: bytes,
    request: Request,
    resumables: ResumableSessionStore,
) -> Any:
    try:
        metadata = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        return make_error_response(400, f"resumable init body is not valid JSON: {e}")
    declared_total_str = request.headers.get("X-Upload-Content-Length")
    declared_total = int(declared_total_str) if declared_total_str else None
    # Stash the full metadata on the session so the final PUT preserves the
    # caller's jobReference and configuration.
    job_config = {"_metadata": metadata}
    sid = resumables.init(
        project=project, job_config=job_config, declared_total=declared_total,
    )
    base = str(request.url).split("?")[0]
    location = f"{base}?upload_id={sid}"
    return Response(
        status_code=200,
        headers={"Location": location},
        content=b"",
    )


async def _handle_resumable_put(
    *,
    project: str,
    upload_id: str,
    body: bytes,
    content_range: str,
    resumables: ResumableSessionStore,
    load_runner: LoadRunner,
    runner: JobRunner,
) -> Any:
    if not upload_id:
        return make_error_response(400, "missing upload_id")
    m = _CONTENT_RANGE_RE.match(content_range or "")
    if not m:
        return make_error_response(400, f"invalid Content-Range: {content_range!r}")
    start = int(m.group(1))
    end = int(m.group(2))
    total_str = m.group(3)
    total = None if total_str == "*" else int(total_str)
    try:
        complete = resumables.append(upload_id, body, start=start, end=end, total=total)
    except ResumableSessionNotFound:
        return make_error_response(410, f"resumable session not found: {upload_id}", reason="notFound")
    except OutOfOrderChunk as e:
        return make_error_response(400, str(e))
    sess = resumables.get(upload_id)
    if not complete:
        return Response(
            status_code=308,
            headers={"Range": f"bytes=0-{sess.received_total - 1}"},
            content=b"",
        )
    metadata = sess.job_config["_metadata"]
    data = bytes(sess.chunks)
    resumables.drop(upload_id)
    return await _run_load_and_persist(
        project=project,
        metadata=metadata,
        data=data,
        load_runner=load_runner,
        runner=runner,
    )


def _gen_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"
