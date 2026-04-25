"""Upload handlers: /upload/bigquery/v2/projects/{p}/jobs (spec §3).

Two upload styles share the endpoint, dispatched on uploadType:

- multipart: single POST with a multipart/related body (metadata JSON +
  data payload). Runs the load synchronously and returns the Job.
- resumable: init POST returns a session URL; PUT chunks accumulate into
  an in-memory buffer; the final PUT runs the load. (Added in next task.)
"""

import email
import json
import uuid
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.errors import bigquery_error_response
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_project_id,
)


class MultipartParseError(ValueError):
    pass


def _envelope(status_code: int, message: str, reason: str = "invalid") -> JSONResponse:
    status_str = "INVALID_ARGUMENT" if reason == "invalid" else reason.upper()
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": status_code,
                "message": message,
                "errors": [{"reason": reason, "message": message, "domain": "global"}],
                "status": status_str,
            }
        },
    )


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
) -> APIRouter:
    router = APIRouter(prefix="/upload/bigquery/v2/projects")

    @router.post("/{project}/jobs")
    async def upload_job(
        project: str,
        request: Request,
        uploadType: str = "",  # noqa: N803 — query param name matches BQ API
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
            # Resumable handler added in the next task — placeholder for now.
            return _envelope(400, "resumable uploads not yet implemented")
        return _envelope(400, f"Unsupported uploadType: {uploadType!r}")

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
        return _envelope(400, str(e))
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
    from gcp_local.services.bigquery.routes.jobs import _job_to_api

    return _job_to_api(rec)


def _gen_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"
