"""Integration tests driving the emulator with the real google-cloud-secret-manager client."""

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import grpc
import pytest
import pytest_asyncio
from google.api_core import exceptions as gce
from google.cloud import secretmanager_v1
from google.cloud.secretmanager_v1.services.secret_manager_service.transports.grpc import (
    SecretManagerServiceGrpcTransport,
)
from google.iam.v1 import iam_policy_pb2, policy_pb2
from google.protobuf.field_mask_pb2 import FieldMask

from gcp_local.generated.google.cloud.secretmanager.v1 import (
    resources_pb2,
    service_pb2,
    service_pb2_grpc,
)
from gcp_local.services.metadata.tokens import build_access_token


@pytest.fixture
def client(emulator):
    channel = grpc.insecure_channel(f"127.0.0.1:{emulator['secret_manager_port']}")
    transport = SecretManagerServiceGrpcTransport(channel=channel)
    return secretmanager_v1.SecretManagerServiceClient(transport=transport)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


async def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"port {port} did not open within {timeout}s")


@pytest_asyncio.fixture
async def iam_sm_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[int]:
    """Start a Secret Manager instance with IAM enforcement enabled on a free port."""
    monkeypatch.setenv("SECRET_MANAGER_ENFORCE_IAM", "1")

    from gcp_local.core.context import Context
    from gcp_local.services.secret_manager import SecretManagerService

    port = _free_port()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"secret_manager": port})
    svc = SecretManagerService()
    await svc.start(ctx)
    await _wait_for_port(port)
    yield port
    await svc.stop()


def _stub(port: int) -> service_pb2_grpc.SecretManagerServiceStub:
    return service_pb2_grpc.SecretManagerServiceStub(grpc.insecure_channel(f"127.0.0.1:{port}"))


def _meta(email: str) -> list[tuple[str, str]]:
    """Build gRPC call metadata carrying a stub token for the given SA email."""
    token = build_access_token(email)["access_token"]
    return [("authorization", f"Bearer {token}")]


async def test_create_get_list_delete_secret(client):
    parent = "projects/p1"
    secret = secretmanager_v1.Secret(labels={"env": "dev"})
    created = await asyncio.to_thread(
        client.create_secret,
        request={"parent": parent, "secret_id": "my-secret", "secret": secret},
    )
    assert created.name == "projects/p1/secrets/my-secret"
    assert dict(created.labels) == {"env": "dev"}

    got = await asyncio.to_thread(client.get_secret, request={"name": created.name})
    assert got.name == created.name

    listed = await asyncio.to_thread(lambda: list(client.list_secrets(request={"parent": parent})))
    assert any(s.name == created.name for s in listed)

    await asyncio.to_thread(client.delete_secret, request={"name": created.name})
    with pytest.raises(gce.NotFound):
        await asyncio.to_thread(client.get_secret, request={"name": created.name})


async def test_add_and_access_secret_version(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    added = await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"hello"}},
    )
    assert added.name == f"{parent}/secrets/s/versions/1"
    accessed = await asyncio.to_thread(client.access_secret_version, request={"name": added.name})
    assert accessed.payload.data == b"hello"
    assert accessed.payload.data_crc32c != 0


async def test_access_latest_alias_returns_newest_enabled(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"v1"}},
    )
    await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"v2"}},
    )
    latest = await asyncio.to_thread(
        client.access_secret_version,
        request={"name": f"{parent}/secrets/s/versions/latest"},
    )
    assert latest.payload.data == b"v2"


async def test_disable_destroy_blocks_access(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    v = await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"secret"}},
    )
    await asyncio.to_thread(client.disable_secret_version, request={"name": v.name})
    with pytest.raises(gce.FailedPrecondition):
        await asyncio.to_thread(client.access_secret_version, request={"name": v.name})
    await asyncio.to_thread(client.enable_secret_version, request={"name": v.name})
    again = await asyncio.to_thread(client.access_secret_version, request={"name": v.name})
    assert again.payload.data == b"secret"
    await asyncio.to_thread(client.destroy_secret_version, request={"name": v.name})
    with pytest.raises(gce.FailedPrecondition):
        await asyncio.to_thread(client.access_secret_version, request={"name": v.name})


async def test_update_secret_labels_only(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(labels={"old": "1"}),
        },
    )
    updated = await asyncio.to_thread(
        client.update_secret,
        request={
            "secret": secretmanager_v1.Secret(
                name=f"{parent}/secrets/s",
                labels={"new": "2"},
                annotations={"ann": "x"},
            ),
            "update_mask": FieldMask(paths=["labels"]),
        },
    )
    assert dict(updated.labels) == {"new": "2"}
    assert dict(updated.annotations) == {}


async def test_list_secret_versions(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    for _ in range(3):
        await asyncio.to_thread(
            client.add_secret_version,
            request={"parent": f"{parent}/secrets/s", "payload": {"data": b"p"}},
        )
    versions = await asyncio.to_thread(
        lambda: list(client.list_secret_versions(request={"parent": f"{parent}/secrets/s"}))
    )
    ids = sorted(int(v.name.rsplit("/", 1)[1]) for v in versions)
    assert ids == [1, 2, 3]


async def test_get_secret_not_found_raises(client):
    with pytest.raises(gce.NotFound):
        await asyncio.to_thread(client.get_secret, request={"name": "projects/p1/secrets/nope"})


# ---------------------------------------------------------------------------
# IAM: accept-and-store (enforcement off — default)
# ---------------------------------------------------------------------------


async def test_set_and_get_iam_policy_roundtrip(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={"parent": parent, "secret_id": "s", "secret": secretmanager_v1.Secret()},
    )
    resource = f"{parent}/secrets/s"
    policy = policy_pb2.Policy(
        bindings=[
            policy_pb2.Binding(
                role="roles/secretmanager.viewer",
                members=["serviceAccount:reader@local-dev.iam.gserviceaccount.com"],
            )
        ]
    )
    set_resp = await asyncio.to_thread(
        client.set_iam_policy,
        request={"resource": resource, "policy": policy},
    )
    assert len(set_resp.bindings) == 1
    assert set_resp.bindings[0].role == "roles/secretmanager.viewer"

    get_resp = await asyncio.to_thread(client.get_iam_policy, request={"resource": resource})
    assert get_resp.bindings[0].role == "roles/secretmanager.viewer"
    assert "serviceAccount:reader@local-dev.iam.gserviceaccount.com" in list(
        get_resp.bindings[0].members
    )


async def test_test_iam_permissions_without_enforcement_reflects_all(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={"parent": parent, "secret_id": "s", "secret": secretmanager_v1.Secret()},
    )
    requested = ["secretmanager.secrets.get", "secretmanager.versions.access"]
    resp = await asyncio.to_thread(
        client.test_iam_permissions,
        request={"resource": f"{parent}/secrets/s", "permissions": requested},
    )
    assert set(resp.permissions) == set(requested)


# ---------------------------------------------------------------------------
# IAM: enforcement on (SECRET_MANAGER_ENFORCE_IAM=1)
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "admin@local-dev.iam.gserviceaccount.com"
READER_EMAIL = "reader@local-dev.iam.gserviceaccount.com"
ACCESSOR_EMAIL = "accessor@local-dev.iam.gserviceaccount.com"


async def _call(stub_method, *args, meta: list | None = None, **kwargs):
    """Run a synchronous gRPC stub call in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(lambda: stub_method(*args, metadata=meta or [], **kwargs))


@pytest.mark.asyncio
async def test_iam_enforcement_allows_caller_with_correct_role(
    iam_sm_port: int,
) -> None:
    stub = _stub(iam_sm_port)

    await _call(
        stub.CreateSecret,
        service_pb2.CreateSecretRequest(
            parent="projects/p1",
            secret_id="s",
            secret=resources_pb2.Secret(),
        ),
    )
    await _call(
        stub.SetIamPolicy,
        iam_policy_pb2.SetIamPolicyRequest(
            resource="projects/p1/secrets/s",
            policy=policy_pb2.Policy(
                bindings=[
                    policy_pb2.Binding(
                        role="roles/secretmanager.viewer",
                        members=[f"serviceAccount:{READER_EMAIL}"],
                    ),
                ]
            ),
        ),
    )
    resp = await _call(
        stub.GetSecret,
        service_pb2.GetSecretRequest(name="projects/p1/secrets/s"),
        meta=_meta(READER_EMAIL),
    )
    assert resp.name == "projects/p1/secrets/s"


@pytest.mark.asyncio
async def test_iam_enforcement_blocks_caller_without_role(
    iam_sm_port: int,
) -> None:
    stub = _stub(iam_sm_port)

    await _call(
        stub.CreateSecret,
        service_pb2.CreateSecretRequest(
            parent="projects/p1",
            secret_id="s",
            secret=resources_pb2.Secret(),
        ),
    )
    await _call(
        stub.SetIamPolicy,
        iam_policy_pb2.SetIamPolicyRequest(
            resource="projects/p1/secrets/s",
            policy=policy_pb2.Policy(
                bindings=[
                    policy_pb2.Binding(
                        role="roles/secretmanager.viewer",
                        members=[f"serviceAccount:{READER_EMAIL}"],
                    ),
                ]
            ),
        ),
    )

    with pytest.raises(grpc.RpcError) as exc_info:
        await _call(
            stub.GetSecret,
            service_pb2.GetSecretRequest(name="projects/p1/secrets/s"),
            meta=_meta("nobody@local-dev.iam.gserviceaccount.com"),
        )
    assert exc_info.value.code() == grpc.StatusCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_iam_enforcement_accessor_can_read_version_viewer_cannot(
    iam_sm_port: int,
) -> None:
    stub = _stub(iam_sm_port)

    await _call(
        stub.CreateSecret,
        service_pb2.CreateSecretRequest(
            parent="projects/p1",
            secret_id="s",
            secret=resources_pb2.Secret(),
        ),
    )
    await _call(
        stub.AddSecretVersion,
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/s",
            payload=resources_pb2.SecretPayload(data=b"top-secret"),
        ),
    )
    await _call(
        stub.SetIamPolicy,
        iam_policy_pb2.SetIamPolicyRequest(
            resource="projects/p1/secrets/s",
            policy=policy_pb2.Policy(
                bindings=[
                    policy_pb2.Binding(
                        role="roles/secretmanager.viewer",
                        members=[f"serviceAccount:{READER_EMAIL}"],
                    ),
                    policy_pb2.Binding(
                        role="roles/secretmanager.secretAccessor",
                        members=[f"serviceAccount:{ACCESSOR_EMAIL}"],
                    ),
                ]
            ),
        ),
    )

    # accessor can read the secret payload
    resp = await _call(
        stub.AccessSecretVersion,
        service_pb2.AccessSecretVersionRequest(name="projects/p1/secrets/s/versions/1"),
        meta=_meta(ACCESSOR_EMAIL),
    )
    assert resp.payload.data == b"top-secret"

    # viewer cannot access the payload
    with pytest.raises(grpc.RpcError) as exc_info:
        await _call(
            stub.AccessSecretVersion,
            service_pb2.AccessSecretVersionRequest(name="projects/p1/secrets/s/versions/1"),
            meta=_meta(READER_EMAIL),
        )
    assert exc_info.value.code() == grpc.StatusCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_iam_enforcement_empty_policy_allows_all(
    iam_sm_port: int,
) -> None:
    """No policy set → allow all (backward-compatible default)."""
    stub = _stub(iam_sm_port)

    await _call(
        stub.CreateSecret,
        service_pb2.CreateSecretRequest(
            parent="projects/p1",
            secret_id="s",
            secret=resources_pb2.Secret(),
        ),
    )
    resp = await _call(
        stub.GetSecret,
        service_pb2.GetSecretRequest(name="projects/p1/secrets/s"),
        meta=_meta("anyone@local-dev.iam.gserviceaccount.com"),
    )
    assert resp.name == "projects/p1/secrets/s"


@pytest.mark.asyncio
async def test_iam_test_permissions_reflects_granted_permissions_only(
    iam_sm_port: int,
) -> None:
    stub = _stub(iam_sm_port)

    await _call(
        stub.CreateSecret,
        service_pb2.CreateSecretRequest(
            parent="projects/p1",
            secret_id="s",
            secret=resources_pb2.Secret(),
        ),
    )
    await _call(
        stub.SetIamPolicy,
        iam_policy_pb2.SetIamPolicyRequest(
            resource="projects/p1/secrets/s",
            policy=policy_pb2.Policy(
                bindings=[
                    policy_pb2.Binding(
                        role="roles/secretmanager.viewer",
                        members=[f"serviceAccount:{READER_EMAIL}"],
                    ),
                ]
            ),
        ),
    )

    resp = await _call(
        stub.TestIamPermissions,
        iam_policy_pb2.TestIamPermissionsRequest(
            resource="projects/p1/secrets/s",
            permissions=["secretmanager.secrets.get", "secretmanager.versions.access"],
        ),
        meta=_meta(READER_EMAIL),
    )
    # viewer has .get but not .access
    assert "secretmanager.secrets.get" in resp.permissions
    assert "secretmanager.versions.access" not in resp.permissions
