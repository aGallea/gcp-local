from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_metadata_update
from gcp_local.services.gcs.ids import rfc3339_now
from gcp_local.services.gcs.preconditions import (
    PreconditionFailed,
    Preconditions,
    evaluate_preconditions,
)
from gcp_local.services.gcs.routes._serialize import object_to_api_dict
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectNotFound,
)


def register_object_write_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
) -> None:
    @router.patch("/storage/v1/b/{bucket}/o/{name:path}")
    async def patch_object(
        bucket: str,
        name: str,
        request: Request,
        ifMetagenerationMatch: int | None = Query(default=None, alias="ifMetagenerationMatch"),
        ifMetagenerationNotMatch: int | None = Query(
            default=None, alias="ifMetagenerationNotMatch"
        ),
    ) -> JSONResponse:
        try:
            current = await storage.get_object(bucket, name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {name!r} not found")

        try:
            evaluate_preconditions(
                Preconditions(
                    if_metageneration_match=ifMetagenerationMatch,
                    if_metageneration_not_match=ifMetagenerationNotMatch,
                ),
                current=current,
            )
        except PreconditionFailed as e:
            return error_response(412, "conditionNotMet", str(e))

        patch = await request.json()

        updated = current.model_copy(
            update={
                "content_type": patch.get("contentType", current.content_type),
                "content_encoding": patch.get("contentEncoding", current.content_encoding),
                "content_language": patch.get("contentLanguage", current.content_language),
                "content_disposition": patch.get("contentDisposition", current.content_disposition),
                "cache_control": patch.get("cacheControl", current.cache_control),
                "metadata": patch.get("metadata", current.metadata),
                "metageneration": current.metageneration + 1,
                "updated": rfc3339_now(),
            }
        )
        await storage.update_object_metadata(updated)
        await publish_metadata_update(state_hub, updated)
        return JSONResponse(object_to_api_dict(updated, str(request.base_url)))
