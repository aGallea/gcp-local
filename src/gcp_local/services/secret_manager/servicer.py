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
    parse_version_name,
    validate_secret_id,
)
from gcp_local.services.secret_manager.storage import (
    InvalidStateTransition,
    SecretAlreadyExists,
    SecretManagerStorage,
    SecretNotFound,
    VersionNotFound,
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

    # --- version lifecycle -----------------------------------------------

    async def AddSecretVersion(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.parent)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            version = await self._storage.add_version(project, sid, bytes(request.payload.data))
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.parent!r} not found")
        return _version_to_proto(project, sid, version)

    async def GetSecretVersion(self, request: Any, context: Any) -> Any:
        try:
            project, sid, vid_raw = parse_version_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        if vid_raw == "latest":
            try:
                rec = await self._storage.get_secret(project, sid)
            except SecretNotFound:
                await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
            v = rec.highest_enabled_version()
            if v is None:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"no enabled version for secret {sid!r}",
                )
            assert v is not None
            return _version_to_proto(project, sid, v)
        try:
            vid = int(vid_raw)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"bad version id: {vid_raw!r}")
        try:
            version = await self._storage.get_version(project, sid, vid)
        except (SecretNotFound, VersionNotFound):
            await context.abort(grpc.StatusCode.NOT_FOUND, f"version {request.name!r} not found")
        return _version_to_proto(project, sid, version)

    async def ListSecretVersions(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.parent)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            items, next_token = await self._storage.list_versions(
                project,
                sid,
                page_size=request.page_size or None,
                page_token=request.page_token or None,
            )
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
        return service_pb2.ListSecretVersionsResponse(
            versions=[_version_to_proto(project, sid, v) for v in items],
            next_page_token=next_token or "",
            total_size=len(items),
        )

    async def AccessSecretVersion(self, request: Any, context: Any) -> Any:
        try:
            project, sid, vid_raw = parse_version_name(request.name)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

        v: SecretVersion
        if vid_raw == "latest":
            try:
                rec = await self._storage.get_secret(project, sid)
            except SecretNotFound:
                await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
            enabled = rec.highest_enabled_version()
            if enabled is None:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"no enabled version for secret {sid!r}",
                )
            assert enabled is not None
            v = enabled
        else:
            try:
                vid = int(vid_raw)
            except ValueError:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    f"bad version id: {vid_raw!r}",
                )
            try:
                v = await self._storage.get_version(project, sid, vid)
            except (SecretNotFound, VersionNotFound):
                await context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"version {request.name!r} not found",
                )
            if v.state != SecretVersionState.ENABLED:
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"version {request.name!r} is in state {v.state.value}",
                )

        return service_pb2.AccessSecretVersionResponse(
            name=build_version_name(project, sid, v.id),
            payload=resources_pb2.SecretPayload(data=v.payload, data_crc32c=v.data_crc32c),
        )

    async def _set_state(
        self, request_name: str, new_state: SecretVersionState, context: Any
    ) -> Any:
        try:
            project, sid, vid_raw = parse_version_name(request_name)
            vid = int(vid_raw)
        except (InvalidResourceName, ValueError) as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            version = await self._storage.update_version_state(project, sid, vid, new_state)
        except (SecretNotFound, VersionNotFound):
            await context.abort(grpc.StatusCode.NOT_FOUND, f"version {request_name!r} not found")
        except InvalidStateTransition as e:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        return _version_to_proto(project, sid, version)

    async def EnableSecretVersion(self, request: Any, context: Any) -> Any:
        return await self._set_state(request.name, SecretVersionState.ENABLED, context)

    async def DisableSecretVersion(self, request: Any, context: Any) -> Any:
        return await self._set_state(request.name, SecretVersionState.DISABLED, context)

    async def DestroySecretVersion(self, request: Any, context: Any) -> Any:
        return await self._set_state(request.name, SecretVersionState.DESTROYED, context)
