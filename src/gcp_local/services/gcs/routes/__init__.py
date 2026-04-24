from fastapi import APIRouter

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes.buckets import register_bucket_routes
from gcp_local.services.gcs.routes.objects_read import register_object_read_routes
from gcp_local.services.gcs.routes.objects_write import register_object_write_routes
from gcp_local.services.gcs.routes.uploads import register_upload_routes
from gcp_local.services.gcs.storage import GcsStorage


def build_router(
    *,
    storage: GcsStorage,
    state_hub: StateHub,
    generations: GenerationCounter,
) -> APIRouter:
    r = APIRouter()
    register_bucket_routes(r, storage=storage)
    register_object_read_routes(r, storage=storage, state_hub=state_hub)
    register_object_write_routes(r, storage=storage, state_hub=state_hub)
    register_upload_routes(r, storage=storage, state_hub=state_hub, generations=generations)
    return r
