import base64

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import JSONResponse

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_delete
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectNotFound,
)


def _encode_page_token(last_name: str) -> str:
    return base64.urlsafe_b64encode(last_name.encode()).decode()


def _decode_page_token(token: str) -> str:
    return base64.urlsafe_b64decode(token.encode()).decode()


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    if not header.startswith("bytes="):
        return None
    rng = header[len("bytes=") :]
    if "-" not in rng:
        return None
    lo_s, hi_s = rng.split("-", 1)
    lo = int(lo_s) if lo_s else 0
    hi = int(hi_s) if hi_s else size - 1
    if lo < 0 or hi >= size or lo > hi:
        return None
    return lo, hi


def register_object_read_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
) -> None:
    @router.get("/storage/v1/b/{bucket}/o")
    async def list_objects(
        bucket: str,
        prefix: str = "",
        delimiter: str | None = None,
        maxResults: int | None = Query(default=None, alias="maxResults"),
        pageToken: str | None = Query(default=None, alias="pageToken"),
    ) -> JSONResponse:
        start_after = _decode_page_token(pageToken) if pageToken else None
        try:
            objects, prefixes = await storage.list_objects_with_prefixes(
                bucket,
                prefix=prefix,
                delimiter=delimiter,
                max_results=maxResults,
                start_after=start_after,
            )
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")

        body: dict[str, object] = {
            "items": [o.model_dump(by_alias=True) for o in objects],
        }
        if prefixes:
            body["prefixes"] = prefixes
        if maxResults is not None and len(objects) == maxResults:
            body["nextPageToken"] = _encode_page_token(objects[-1].name)
        return JSONResponse(body)

    @router.get("/storage/v1/b/{bucket}/o/{name:path}")
    async def get_object(
        bucket: str,
        name: str,
        alt: str = "json",
        range_header: str | None = Header(default=None, alias="Range"),
    ) -> Response:
        try:
            record = await storage.get_object(bucket, name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {name!r} not found")

        if alt != "media":
            return JSONResponse(record.model_dump(by_alias=True))

        data = await storage.get_object_bytes(bucket, name)
        if range_header:
            parsed = _parse_range(range_header, len(data))
            if parsed is None:
                return error_response(416, "invalid", "range not satisfiable")
            lo, hi = parsed
            partial = data[lo : hi + 1]
            return Response(
                content=partial,
                status_code=206,
                headers={
                    "Content-Range": f"bytes {lo}-{hi}/{len(data)}",
                    "Content-Type": record.content_type,
                },
            )
        return Response(
            content=data,
            media_type=record.content_type,
        )

    @router.delete("/storage/v1/b/{bucket}/o/{name:path}")
    async def delete_object(bucket: str, name: str) -> Response:
        try:
            existing = await storage.get_object(bucket, name)
            await storage.delete_object(bucket, name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {name!r} not found")
        await publish_delete(state_hub, existing)
        return Response(status_code=204)
