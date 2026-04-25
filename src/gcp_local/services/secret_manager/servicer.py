from __future__ import annotations

import logging
from typing import Any

import grpc
from google.protobuf import empty_pb2
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.generated.google.cloud.secretmanager.v1 import (
    resources_pb2,
    service_pb2,
    service_pb2_grpc,
)
from gcp_local.services.gcs.ids import rfc3339_now
from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersion,
    SecretVersionState,
)
from gcp_local.services.secret_manager.names import (
    InvalidResourceName,
    build_secret_name,
    build_version_name,
    parse_secret_name,
    validate_secret_id,
)
from gcp_local.services.secret_manager.storage import (
    SecretAlreadyExists,
    SecretManagerStorage,
    SecretNotFound,
)

log = logging.getLogger(__name__)


def _parse_parent(parent: str) -> str:
    """projects/<project> -> <project>. Raises if shape wrong."""
    prefix = "projects/"
    if not parent.startswith(prefix) or len(parent) <= len(prefix):
        raise InvalidResourceName(f"bad parent: {parent!r}")
    project = parent[len(prefix) :]
    if "/" in project:
        raise InvalidResourceName(f"bad parent: {parent!r}")
    return project


def _timestamp(rfc3339: str | None) -> Timestamp:
    ts = Timestamp()
    if rfc3339:
        ts.FromJsonString(rfc3339)
    return ts


def _record_to_proto(r: SecretRecord) -> resources_pb2.Secret:
    return resources_pb2.Secret(
        name=build_secret_name(r.project, r.secret_id),
        create_time=_timestamp(r.create_time),
        labels=dict(r.labels),
        annotations=dict(r.annotations),
    )


def _version_to_proto(
    project: str, secret_id: str, v: SecretVersion
) -> resources_pb2.SecretVersion:
    state_map = {
        SecretVersionState.ENABLED: resources_pb2.SecretVersion.ENABLED,
        SecretVersionState.DISABLED: resources_pb2.SecretVersion.DISABLED,
        SecretVersionState.DESTROYED: resources_pb2.SecretVersion.DESTROYED,
    }
    return resources_pb2.SecretVersion(
        name=build_version_name(project, secret_id, v.id),
        create_time=_timestamp(v.create_time),
        destroy_time=_timestamp(v.destroy_time) if v.destroy_time else Timestamp(),
        state=state_map[v.state],
    )


class SecretManagerServicer(service_pb2_grpc.SecretManagerServiceServicer):
    def __init__(self, *, storage: SecretManagerStorage) -> None:
        self._storage = storage

    async def CreateSecret(self, request: Any, context: Any) -> Any:
        try:
            project = _parse_parent(request.parent)
            validate_secret_id(request.secret_id)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        rec = SecretRecord(
            project=project,
            secret_id=request.secret_id,
            labels=dict(request.secret.labels),
            annotations=dict(request.secret.annotations),
            create_time=rfc3339_now(),
        )
        try:
            await self._storage.create_secret(rec)
        except SecretAlreadyExists:
            await context.abort(
                grpc.StatusCode.ALREADY_EXISTS,
                f"secret {request.secret_id!r} already exists",
            )
        return _record_to_proto(rec)

    async def GetSecret(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.name!r} not found")
        return _record_to_proto(rec)

    async def ListSecrets(self, request: Any, context: Any) -> Any:
        try:
            project = _parse_parent(request.parent)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        page_size = request.page_size or None
        page_token = request.page_token or None
        items, next_token = await self._storage.list_secrets(
            project, page_size=page_size, page_token=page_token
        )
        return service_pb2.ListSecretsResponse(
            secrets=[_record_to_proto(r) for r in items],
            next_page_token=next_token or "",
            total_size=len(items),
        )

    async def UpdateSecret(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.secret.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(
                grpc.StatusCode.NOT_FOUND,
                f"secret {request.secret.name!r} not found",
            )
        mask = set(request.update_mask.paths)
        if "labels" in mask:
            rec.labels = dict(request.secret.labels)
        if "annotations" in mask:
            rec.annotations = dict(request.secret.annotations)
        await self._storage.update_secret(rec)
        return _record_to_proto(rec)

    async def DeleteSecret(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            await self._storage.delete_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.name!r} not found")
        return empty_pb2.Empty()
