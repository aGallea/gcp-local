from typing import Any

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.models import ObjectRecord

EVENT_FINALIZE = "gcs.object.finalize"
EVENT_METADATA_UPDATE = "gcs.object.metadata_update"
EVENT_DELETE = "gcs.object.delete"


def build_event_payload(record: ObjectRecord) -> dict[str, Any]:
    return {
        "bucket": record.bucket,
        "name": record.name,
        "generation": record.generation,
        "metageneration": record.metageneration,
        "size": record.size,
        "contentType": record.content_type,
        "md5Hash": record.md5_hash,
        "crc32c": record.crc32c,
        "timeCreated": record.time_created,
        "updated": record.updated,
        "metadata": dict(record.metadata),
    }


async def _publish(hub: StateHub | None, topic: str, record: ObjectRecord) -> None:
    if hub is None:
        return
    await hub.publish(topic, build_event_payload(record))


async def publish_finalize(hub: StateHub | None, record: ObjectRecord) -> None:
    await _publish(hub, EVENT_FINALIZE, record)


async def publish_metadata_update(hub: StateHub | None, record: ObjectRecord) -> None:
    await _publish(hub, EVENT_METADATA_UPDATE, record)


async def publish_delete(hub: StateHub | None, record: ObjectRecord) -> None:
    await _publish(hub, EVENT_DELETE, record)
