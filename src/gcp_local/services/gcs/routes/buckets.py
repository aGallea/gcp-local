from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.ids import rfc3339_now
from gcp_local.services.gcs.models import BucketMeta
from gcp_local.services.gcs.routes._serialize import (
    bucket_to_api_dict,
    storage_layout_dict,
)
from gcp_local.services.gcs.storage import (
    BucketAlreadyExists,
    BucketNotFound,
    GcsStorage,
)


class _CreateBody(BaseModel):
    name: str
    location: str | None = None
    storageClass: str | None = None


def register_bucket_routes(router: APIRouter, *, storage: GcsStorage) -> None:

    @router.post("/storage/v1/b")
    async def create_bucket(body: _CreateBody, request: Request) -> JSONResponse:
        bucket = BucketMeta(
            name=body.name,
            time_created=rfc3339_now(),
            location=body.location or "US",
            storage_class=body.storageClass or "STANDARD",
        )
        try:
            await storage.create_bucket(bucket)
        except BucketAlreadyExists:
            return error_response(409, "conflict", f"bucket {body.name!r} already exists")
        return JSONResponse(bucket_to_api_dict(bucket, str(request.base_url)))

    @router.get("/storage/v1/b")
    async def list_buckets(request: Request) -> JSONResponse:
        buckets = await storage.list_buckets()
        base_url = str(request.base_url)
        return JSONResponse(
            {
                "kind": "storage#buckets",
                "items": [bucket_to_api_dict(b, base_url) for b in buckets],
            }
        )

    @router.get("/storage/v1/b/{bucket}/storageLayout")
    async def get_storage_layout(bucket: str) -> JSONResponse:
        try:
            b = await storage.get_bucket(bucket)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        return JSONResponse(storage_layout_dict(b))

    @router.get("/storage/v1/b/{bucket}")
    async def get_bucket(bucket: str, request: Request) -> JSONResponse:
        try:
            b = await storage.get_bucket(bucket)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        return JSONResponse(bucket_to_api_dict(b, str(request.base_url)))

    @router.delete("/storage/v1/b/{bucket}")
    async def delete_bucket(bucket: str) -> Response:
        try:
            await storage.delete_bucket(bucket)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        return Response(status_code=204)
