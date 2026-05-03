"""ui-api GCS endpoints.

Thin presenter layer over ``GcsStorage``. Returns UI-shaped responses
(computed sizes, friendly timestamps, preview metadata) rather than the
Google wire-format that the public REST API on port 4443 emits.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.errors import UiApiError
from gcp_local.services.gcs.storage import (
    BucketAlreadyExists,
    BucketNotFound,
    GcsStorage,
)

# ---- Schemas ---------------------------------------------------------------


class BucketSummary(BaseModel):
    name: str
    location: str
    storage_class: str
    time_created: str


class BucketList(BaseModel):
    buckets: list[BucketSummary]


class CreateBucketRequest(BaseModel):
    name: str
    location: str = "US"


class BlobSummary(BaseModel):
    name: str
    size: int
    content_type: str
    updated: str
    generation: int


class BlobList(BaseModel):
    bucket: str
    prefix: str
    blobs: list[BlobSummary]
    folders: list[str]
    next_page_token: str | None = None


class BlobMetadata(BaseModel):
    bucket: str
    name: str
    size: int
    content_type: str
    time_created: str
    updated: str
    generation: int
    metageneration: int
    md5_hash: str
    crc32c: str
    metadata: dict[str, str]
    preview: "BlobPreview | None" = None


class BlobPreview(BaseModel):
    kind: Literal["text", "json", "image", "none"]
    text: str | None = None
    image_data_url: str | None = None
    truncated: bool = False
    reason: str | None = None  # populated when kind == "none"


BlobMetadata.model_rebuild()


# ---- Helpers ---------------------------------------------------------------


def _get_storage(lc: Lifecycle) -> GcsStorage:
    for svc in lc.services:
        if svc.name == "gcs":
            # Imported lazily so non-gcs builds don't pay the cost.
            from gcp_local.services.gcs.service import GcsService

            assert isinstance(svc, GcsService)
            return svc.storage
    raise UiApiError(
        status_code=503,
        code="service_unavailable",
        message="gcs service is not running",
    )


def _storage_dep(request: Request) -> GcsStorage:
    lc: Lifecycle = request.app.state.lifecycle
    return _get_storage(lc)


StorageDep = Annotated[GcsStorage, Depends(_storage_dep)]


# ---- Endpoints (implemented in subsequent tasks) ---------------------------


def build_gcs_router() -> APIRouter:
    router = APIRouter(prefix="/gcs", tags=["gcs"])

    @router.get("/buckets", response_model=BucketList)
    async def list_buckets(storage: StorageDep) -> BucketList:
        buckets = await storage.list_buckets()
        return BucketList(
            buckets=[
                BucketSummary(
                    name=b.name,
                    location=b.location,
                    storage_class=b.storage_class,
                    time_created=b.time_created,
                )
                for b in buckets
            ],
        )

    @router.post(
        "/buckets",
        response_model=BucketSummary,
        status_code=201,
    )
    async def create_bucket(payload: CreateBucketRequest, storage: StorageDep) -> BucketSummary:
        if not payload.name.strip():
            raise UiApiError(
                status_code=400,
                code="invalid_argument",
                message="bucket name must not be empty",
            )
        from datetime import UTC, datetime

        from gcp_local.services.gcs.models import BucketMeta

        meta = BucketMeta(
            name=payload.name,
            time_created=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            location=payload.location,
        )
        try:
            await storage.create_bucket(meta)
        except BucketAlreadyExists:
            raise UiApiError(
                status_code=409,
                code="already_exists",
                message=f"bucket '{payload.name}' already exists",
            ) from None
        return BucketSummary(
            name=meta.name,
            location=meta.location,
            storage_class=meta.storage_class,
            time_created=meta.time_created,
        )

    @router.delete("/buckets/{bucket}", status_code=204)
    async def delete_bucket(
        bucket: str,
        storage: StorageDep,
        force: bool = Query(default=False),
    ) -> Response:
        try:
            await storage.get_bucket(bucket)
        except BucketNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"bucket '{bucket}' not found",
            ) from None
        objects, _ = await storage.list_objects_with_prefixes(bucket)
        if objects:
            if not force:
                raise UiApiError(
                    status_code=409,
                    code="not_empty",
                    message=f"bucket '{bucket}' is not empty; pass force=true to delete contents",
                )
            for obj in objects:
                await storage.delete_object(bucket, obj.name)
        await storage.delete_bucket(bucket)
        return Response(status_code=204)

    @router.get(
        "/buckets/{bucket}/blobs",
        response_model=BlobList,
    )
    async def list_blobs(
        bucket: str,
        storage: StorageDep,
        prefix: str = Query(default=""),
        delimiter: str | None = Query(default=None),
        page_size: int = Query(default=1000, ge=1, le=1000),
        page_token: str | None = Query(default=None),
    ) -> BlobList:
        try:
            await storage.get_bucket(bucket)
        except BucketNotFound:
            raise UiApiError(
                status_code=404,
                code="not_found",
                message=f"bucket '{bucket}' not found",
            ) from None
        objects, prefixes = await storage.list_objects_with_prefixes(
            bucket,
            prefix=prefix,
            delimiter=delimiter,
            max_results=page_size + 1,
            start_after=page_token,
        )
        next_token: str | None = None
        if len(objects) > page_size:
            objects = objects[:page_size]
            next_token = objects[-1].name
        return BlobList(
            bucket=bucket,
            prefix=prefix,
            blobs=[
                BlobSummary(
                    name=o.name,
                    size=o.size,
                    content_type=o.content_type,
                    updated=o.updated,
                    generation=o.generation,
                )
                for o in objects
            ],
            folders=sorted(prefixes),
            next_page_token=next_token,
        )

    return router
