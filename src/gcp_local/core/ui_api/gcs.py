"""ui-api GCS endpoints.

Thin presenter layer over ``GcsStorage``. Returns UI-shaped responses
(computed sizes, friendly timestamps, preview metadata) rather than the
Google wire-format that the public REST API on port 4443 emits.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.errors import UiApiError
from gcp_local.services.gcs.storage import (
    BucketNotFound,  # noqa: F401  -- used by endpoints in subsequent tasks
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
    return router
