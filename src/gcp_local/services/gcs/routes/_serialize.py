"""Shared JSON-API serialization helpers for GCS routes.

Real Google Cloud Storage object/bucket metadata responses include a few
fields (``kind``, ``id``, ``selfLink``, ``mediaLink``) that some clients
rely on. The official ``google-cloud-storage`` Python library tolerates
their absence, but ``gcloud storage`` (which goes through apitools) does
not — its download path reads ``object_resource.metadata.mediaLink`` and
crashes with a bytes/str ``TypeError`` when it ends up ``None``.

These helpers add the missing fields, computed from the live request URL
so they point back at the emulator rather than at ``storage.googleapis.com``.
"""

from typing import Any
from urllib.parse import quote

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord


def _normalize_base_url(base_url: str) -> str:
    """Strip trailing slash so we can concatenate paths without doubling it."""
    return base_url.rstrip("/")


def object_to_api_dict(record: ObjectRecord, base_url: str) -> dict[str, Any]:
    """Serialize an ObjectRecord to the JSON-API shape gcloud expects.

    ``base_url`` is the request's base URL (e.g. ``http://localhost:9023``);
    the resulting ``selfLink`` and ``mediaLink`` will route back through the
    emulator on the same host.
    """
    base = _normalize_base_url(base_url)
    name_quoted = quote(record.name, safe="")
    body = record.model_dump(by_alias=True)
    body["kind"] = "storage#object"
    body["id"] = f"{record.bucket}/{record.name}/{record.generation}"
    body["selfLink"] = f"{base}/storage/v1/b/{record.bucket}/o/{name_quoted}"
    body["mediaLink"] = (
        f"{base}/download/storage/v1/b/{record.bucket}/o/{name_quoted}"
        f"?generation={record.generation}&alt=media"
    )
    body["storageClass"] = "STANDARD"
    return body


def bucket_to_api_dict(bucket: BucketMeta, base_url: str) -> dict[str, Any]:
    """Serialize a BucketMeta to the JSON-API shape gcloud expects."""
    base = _normalize_base_url(base_url)
    body = bucket.model_dump(by_alias=True)
    body["kind"] = "storage#bucket"
    body["id"] = bucket.name
    body["selfLink"] = f"{base}/storage/v1/b/{bucket.name}"
    return body


def storage_layout_dict(bucket: BucketMeta) -> dict[str, Any]:
    """Build the response for ``GET /storage/v1/b/<bucket>/storageLayout``.

    gcloud's storage commands probe this endpoint to discover bucket
    properties (location type, hierarchical-namespace flag) before
    downloads. We return a minimal, stable shape — the values mirror
    what real GCS reports for a multi-region bucket.
    """
    return {
        "kind": "storage#storageLayout",
        "bucket": bucket.name,
        "location": bucket.location,
        "locationType": "multi-region",
        "hierarchicalNamespace": {"enabled": False},
    }
