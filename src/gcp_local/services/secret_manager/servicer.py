from __future__ import annotations

import logging
from typing import Any

import grpc
from google.iam.v1 import iam_policy_pb2, policy_pb2
from google.protobuf import empty_pb2
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.generated.google.cloud.secretmanager.v1 import (
    resources_pb2,
    service_pb2,
    service_pb2_grpc,
)
from gcp_local.services.gcs.ids import rfc3339_now
from gcp_local.services.metadata.tokens import decode_stub_token_email
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

# Maps built-in Secret Manager roles to the permissions they grant.
_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "roles/secretmanager.admin": frozenset(
        {
            "secretmanager.secrets.create",
            "secretmanager.secrets.get",
            "secretmanager.secrets.list",
            "secretmanager.secrets.update",
            "secretmanager.secrets.delete",
            "secretmanager.secrets.setIamPolicy",
            "secretmanager.secrets.getIamPolicy",
            "secretmanager.versions.add",
            "secretmanager.versions.get",
            "secretmanager.versions.list",
            "secretmanager.versions.access",
            "secretmanager.versions.enable",
            "secretmanager.versions.disable",
            "secretmanager.versions.destroy",
        }
    ),
    "roles/secretmanager.secretVersionManager": frozenset(
        {
            "secretmanager.secrets.get",
            "secretmanager.secrets.list",
            "secretmanager.versions.add",
            "secretmanager.versions.get",
            "secretmanager.versions.list",
            "secretmanager.versions.enable",
            "secretmanager.versions.disable",
            "secretmanager.versions.destroy",
        }
    ),
    "roles/secretmanager.secretVersionAdder": frozenset(
        {
            "secretmanager.secrets.get",
            "secretmanager.versions.add",
        }
    ),
    "roles/secretmanager.secretAccessor": frozenset(
        {
            "secretmanager.secrets.get",
            "secretmanager.versions.get",
            "secretmanager.versions.access",
        }
    ),
    "roles/secretmanager.viewer": frozenset(
        {
            "secretmanager.secrets.get",
            "secretmanager.secrets.list",
            "secretmanager.versions.get",
            "secretmanager.versions.list",
        }
    ),
}


def _caller_email(context: Any) -> str | None:
    """Extract the SA email from the gRPC authorization metadata, or None."""
    for key, value in context.invocation_metadata():
        if key.lower() == "authorization" and value.startswith("Bearer "):
            return decode_stub_token_email(value[len("Bearer ") :])
    return None


def _has_permission(policy: dict[str, Any], email: str, permission: str) -> bool:
    """Return True if email holds permission according to policy."""
    candidates = {f"serviceAccount:{email}", "allAuthenticatedUsers", "allUsers"}
    for binding in policy.get("bindings", []):
        role = binding.get("role", "")
        members = set(binding.get("members", []))
        if candidates & members and permission in _ROLE_PERMISSIONS.get(role, frozenset()):
            return True
    return False


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


def _policy_to_proto(policy: dict[str, Any]) -> policy_pb2.Policy:
    bindings = [
        policy_pb2.Binding(role=b["role"], members=b.get("members", []))
        for b in policy.get("bindings", [])
    ]
    return policy_pb2.Policy(version=policy.get("version", 1), bindings=bindings)


def _proto_to_policy(proto: policy_pb2.Policy) -> dict[str, Any]:
    return {
        "version": proto.version or 1,
        "bindings": [{"role": b.role, "members": list(b.members)} for b in proto.bindings],
    }


class SecretManagerServicer(service_pb2_grpc.SecretManagerServiceServicer):
    def __init__(self, *, storage: SecretManagerStorage, enforce_iam: bool = False) -> None:
        self._storage = storage
        self._enforce_iam = enforce_iam

    async def _check_iam(self, context: Any, policy: dict[str, Any], permission: str) -> None:
        """Abort with PERMISSION_DENIED if caller lacks permission.

        No-op when enforcement is disabled or when the secret has no policy
        (empty policy = allow all, preserving pre-IAM behaviour).
        """
        if not self._enforce_iam or not policy.get("bindings"):
            return
        email = _caller_email(context)
        if email is None:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or unrecognized token")
            return
        if not _has_permission(policy, email, permission):
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                f"{email!r} does not have {permission!r} on this secret",
            )

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
        await self._check_iam(context, rec.policy, "secretmanager.secrets.get")
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
        await self._check_iam(context, rec.policy, "secretmanager.secrets.update")
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
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.name!r} not found")
        await self._check_iam(context, rec.policy, "secretmanager.secrets.delete")
        await self._storage.delete_secret(project, sid)
        return empty_pb2.Empty()

    # --- version lifecycle -----------------------------------------------

    async def AddSecretVersion(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.parent)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.parent!r} not found")
        await self._check_iam(context, rec.policy, "secretmanager.versions.add")
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
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
        await self._check_iam(context, rec.policy, "secretmanager.versions.get")
        if vid_raw == "latest":
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
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
        await self._check_iam(context, rec.policy, "secretmanager.versions.list")
        items, next_token = await self._storage.list_versions(
            project,
            sid,
            page_size=request.page_size or None,
            page_token=request.page_token or None,
        )
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

        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {sid!r} not found")
        await self._check_iam(context, rec.policy, "secretmanager.versions.access")

        v: SecretVersion
        if vid_raw == "latest":
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
        self, request_name: str, new_state: SecretVersionState, context: Any, permission: str
    ) -> Any:
        try:
            project, sid, vid_raw = parse_version_name(request_name)
            vid = int(vid_raw)
        except (InvalidResourceName, ValueError) as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"version {request_name!r} not found")
        await self._check_iam(context, rec.policy, permission)
        try:
            version = await self._storage.update_version_state(project, sid, vid, new_state)
        except (SecretNotFound, VersionNotFound):
            await context.abort(grpc.StatusCode.NOT_FOUND, f"version {request_name!r} not found")
        except InvalidStateTransition as e:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        return _version_to_proto(project, sid, version)

    async def EnableSecretVersion(self, request: Any, context: Any) -> Any:
        return await self._set_state(
            request.name, SecretVersionState.ENABLED, context, "secretmanager.versions.enable"
        )

    async def DisableSecretVersion(self, request: Any, context: Any) -> Any:
        return await self._set_state(
            request.name, SecretVersionState.DISABLED, context, "secretmanager.versions.disable"
        )

    async def DestroySecretVersion(self, request: Any, context: Any) -> Any:
        return await self._set_state(
            request.name, SecretVersionState.DESTROYED, context, "secretmanager.versions.destroy"
        )

    # --- IAM -------------------------------------------------------------

    async def SetIamPolicy(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.resource)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.resource!r} not found")
        await self._check_iam(context, rec.policy, "secretmanager.secrets.setIamPolicy")
        policy = _proto_to_policy(request.policy)
        await self._storage.set_iam_policy(project, sid, policy)
        return _policy_to_proto(policy)

    async def GetIamPolicy(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.resource)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.resource!r} not found")
        await self._check_iam(context, rec.policy, "secretmanager.secrets.getIamPolicy")
        policy = await self._storage.get_iam_policy(project, sid)
        return _policy_to_proto(policy)

    async def TestIamPermissions(self, request: Any, context: Any) -> Any:
        try:
            project, sid = parse_secret_name(request.resource)
        except InvalidResourceName as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            rec = await self._storage.get_secret(project, sid)
        except SecretNotFound:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"secret {request.resource!r} not found")

        if not self._enforce_iam or not rec.policy.get("bindings"):
            # Without enforcement, reflect all requested permissions back.
            return iam_policy_pb2.TestIamPermissionsResponse(permissions=list(request.permissions))

        email = _caller_email(context)
        if email is None:
            return iam_policy_pb2.TestIamPermissionsResponse(permissions=[])

        granted = [p for p in request.permissions if _has_permission(rec.policy, email, p)]
        return iam_policy_pb2.TestIamPermissionsResponse(permissions=granted)
