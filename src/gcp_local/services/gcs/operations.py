from dataclasses import dataclass

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import publish_finalize
from gcp_local.services.gcs.ids import (
    GenerationCounter,
    compute_crc32c_b64,
    compute_md5_b64,
    rfc3339_now,
)
from gcp_local.services.gcs.models import ObjectRecord
from gcp_local.services.gcs.preconditions import (
    PreconditionFailed,
    Preconditions,
    evaluate_preconditions,
)
from gcp_local.services.gcs.storage import GcsStorage, ObjectNotFound

MAX_COMPOSE_SOURCES = 32


class InvalidCompose(ValueError):
    pass


@dataclass(frozen=True)
class ComposeSource:
    name: str
    generation: int | None = None
    if_generation_match: int | None = None


async def finalize_object(
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


async def compose_object(
    *,
    storage: GcsStorage,
    generations: GenerationCounter,
    state_hub: StateHub | None,
    bucket: str,
    name: str,
    sources: list[ComposeSource],
    content_type: str,
    user_metadata: dict[str, str],
    preconditions: Preconditions,
) -> ObjectRecord:
    if len(sources) > MAX_COMPOSE_SOURCES:
        raise InvalidCompose(f"compose accepts at most {MAX_COMPOSE_SOURCES} sources")
    if not sources:
        raise InvalidCompose("compose requires at least one source")

    buffers: list[bytes] = []
    for src in sources:
        if src.generation is not None or src.if_generation_match is not None:
            record = await storage.get_object(bucket, src.name)
            if src.generation is not None and record.generation != src.generation:
                raise ObjectNotFound(f"{src.name}#{src.generation}")
            if src.if_generation_match is not None and (
                record.generation != src.if_generation_match
            ):
                raise PreconditionFailed(
                    f"source {src.name!r} ifGenerationMatch={src.if_generation_match} "
                    "does not match"
                )
        buffers.append(await storage.get_object_bytes(bucket, src.name))

    return await finalize_object(
        storage=storage,
        generations=generations,
        state_hub=state_hub,
        bucket=bucket,
        name=name,
        data=b"".join(buffers),
        content_type=content_type,
        user_metadata=user_metadata,
        preconditions=preconditions,
    )
