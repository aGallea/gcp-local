from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.errors import error_response
from gcp_local.services.gcs.events import publish_finalize
from gcp_local.services.gcs.ids import GenerationCounter, rfc3339_now
from gcp_local.services.gcs.models import ObjectRecord
from gcp_local.services.gcs.operations import ComposeSource, InvalidCompose
from gcp_local.services.gcs.operations import compose_object as compose
from gcp_local.services.gcs.preconditions import Preconditions
from gcp_local.services.gcs.routes._serialize import object_to_api_dict
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    GcsStorage,
    ObjectCollision,
    ObjectNotFound,
)


def register_copy_compose_routes(
    router: APIRouter,
    *,
    storage: GcsStorage,
    state_hub: StateHub | None,
    generations: GenerationCounter,
) -> None:
    @router.post("/storage/v1/b/{src_bucket}/o/{src_name}/copyTo/b/{dst_bucket}/o/{dst_name:path}")
    async def copy_object(
        src_bucket: str,
        src_name: str,
        dst_bucket: str,
        dst_name: str,
        request: Request,
    ) -> JSONResponse:
        try:
            src_record = await storage.get_object(src_bucket, src_name)
            src_bytes = await storage.get_object_bytes(src_bucket, src_name)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {src_bucket!r} not found")
        except ObjectNotFound:
            return error_response(404, "notFound", f"object {src_name!r} not found")

        now = rfc3339_now()
        dst_record = ObjectRecord(
            bucket=dst_bucket,
            name=dst_name,
            size=src_record.size,
            generation=generations.next(dst_bucket),
            metageneration=1,
            content_type=src_record.content_type,
            content_encoding=src_record.content_encoding,
            content_language=src_record.content_language,
            content_disposition=src_record.content_disposition,
            cache_control=src_record.cache_control,
            md5_hash=src_record.md5_hash,
            crc32c=src_record.crc32c,
            time_created=now,
            updated=now,
            metadata=dict(src_record.metadata),
        )
        try:
            await storage.put_object(dst_record, src_bytes)
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {dst_bucket!r} not found")
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))
        await publish_finalize(state_hub, dst_record)
        return JSONResponse(object_to_api_dict(dst_record, str(request.base_url)))

    @router.post("/storage/v1/b/{bucket}/o/{name}/compose")
    async def compose_object(
        bucket: str,
        name: str,
        request: Request,
    ) -> JSONResponse:
        body = await request.json()
        sources: list[ComposeSource] = []
        for src in body.get("sourceObjects", []):
            if not src.get("name"):
                return error_response(400, "invalid", "source object missing name")
            sources.append(ComposeSource(name=src["name"]))

        dest_meta = body.get("destination", {})
        try:
            record = await compose(
                storage=storage,
                generations=generations,
                state_hub=state_hub,
                bucket=bucket,
                name=name,
                sources=sources,
                content_type=dest_meta.get("contentType", "application/octet-stream"),
                user_metadata=dest_meta.get("metadata", {}),
                preconditions=Preconditions(),
            )
        except InvalidCompose as e:
            return error_response(400, "invalid", str(e))
        except BucketNotFound:
            return error_response(404, "notFound", f"bucket {bucket!r} not found")
        except ObjectNotFound as e:
            return error_response(404, "notFound", f"object {e.args[0]!r} not found")
        except ObjectCollision as e:
            return error_response(409, "conflict", str(e))
        return JSONResponse(object_to_api_dict(record, str(request.base_url)))
