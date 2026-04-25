import grpc
import pytest

from gcp_local.generated.google.cloud.secretmanager.v1 import resources_pb2, service_pb2
from gcp_local.services.secret_manager.servicer import SecretManagerServicer
from gcp_local.services.secret_manager.storage import InMemoryStorage


class FakeContext:
    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code, details):
        self.aborted = (code, details)
        raise grpc.aio.AioRpcError(code, None, None, details=details)


async def _create(svc, secret_id="x", project="p1"):
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent=f"projects/{project}",
            secret_id=secret_id,
            secret=resources_pb2.Secret(),
        ),
        FakeContext(),
    )


async def test_add_secret_version_returns_id_1():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    result = await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"hello"),
        ),
        FakeContext(),
    )
    assert result.name == "projects/p1/secrets/x/versions/1"


async def test_access_secret_version_returns_payload():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"hello"),
        ),
        FakeContext(),
    )
    result = await svc.AccessSecretVersion(
        service_pb2.AccessSecretVersionRequest(name="projects/p1/secrets/x/versions/1"),
        FakeContext(),
    )
    assert result.name == "projects/p1/secrets/x/versions/1"
    assert result.payload.data == b"hello"
    assert result.payload.data_crc32c != 0


async def test_access_latest_returns_highest_enabled():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v2"),
        ),
        FakeContext(),
    )
    result = await svc.AccessSecretVersion(
        service_pb2.AccessSecretVersionRequest(name="projects/p1/secrets/x/versions/latest"),
        FakeContext(),
    )
    assert result.payload.data == b"v2"


async def test_access_latest_none_enabled_raises_failed_precondition():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    await svc.DisableSecretVersion(
        service_pb2.DisableSecretVersionRequest(name="projects/p1/secrets/x/versions/1"),
        FakeContext(),
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.AccessSecretVersion(
            service_pb2.AccessSecretVersionRequest(name="projects/p1/secrets/x/versions/latest"),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION


async def test_access_disabled_version_fails_precondition():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    await svc.DisableSecretVersion(
        service_pb2.DisableSecretVersionRequest(name="projects/p1/secrets/x/versions/1"),
        FakeContext(),
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.AccessSecretVersion(
            service_pb2.AccessSecretVersionRequest(name="projects/p1/secrets/x/versions/1"),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.FAILED_PRECONDITION


async def test_enable_disable_destroy_cycle():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    await svc.AddSecretVersion(
        service_pb2.AddSecretVersionRequest(
            parent="projects/p1/secrets/x",
            payload=resources_pb2.SecretPayload(data=b"v1"),
        ),
        FakeContext(),
    )
    disabled = await svc.DisableSecretVersion(
        service_pb2.DisableSecretVersionRequest(name="projects/p1/secrets/x/versions/1"),
        FakeContext(),
    )
    assert disabled.state == resources_pb2.SecretVersion.DISABLED
    enabled = await svc.EnableSecretVersion(
        service_pb2.EnableSecretVersionRequest(name="projects/p1/secrets/x/versions/1"),
        FakeContext(),
    )
    assert enabled.state == resources_pb2.SecretVersion.ENABLED
    destroyed = await svc.DestroySecretVersion(
        service_pb2.DestroySecretVersionRequest(name="projects/p1/secrets/x/versions/1"),
        FakeContext(),
    )
    assert destroyed.state == resources_pb2.SecretVersion.DESTROYED


async def test_list_secret_versions():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    for _ in range(3):
        await svc.AddSecretVersion(
            service_pb2.AddSecretVersionRequest(
                parent="projects/p1/secrets/x",
                payload=resources_pb2.SecretPayload(data=b"p"),
            ),
            FakeContext(),
        )
    result = await svc.ListSecretVersions(
        service_pb2.ListSecretVersionsRequest(parent="projects/p1/secrets/x"),
        FakeContext(),
    )
    ids = [int(v.name.rsplit("/", 1)[1]) for v in result.versions]
    assert ids == [1, 2, 3]


async def test_get_secret_version_not_found():
    svc = SecretManagerServicer(storage=InMemoryStorage())
    await _create(svc)
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.GetSecretVersion(
            service_pb2.GetSecretVersionRequest(name="projects/p1/secrets/x/versions/99"),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND
