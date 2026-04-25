import grpc
import pytest
from google.protobuf.field_mask_pb2 import FieldMask

from gcp_local.generated.google.cloud.secretmanager.v1 import resources_pb2, service_pb2
from gcp_local.services.secret_manager.servicer import SecretManagerServicer
from gcp_local.services.secret_manager.storage import InMemoryStorage


class FakeContext:
    """Minimal grpc.aio.ServicerContext substitute for unit tests."""

    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise grpc.aio.AioRpcError(code, None, None, details=details)


def servicer() -> SecretManagerServicer:
    return SecretManagerServicer(storage=InMemoryStorage())


async def test_create_secret_returns_proto():
    svc = servicer()
    req = service_pb2.CreateSecretRequest(
        parent="projects/p1",
        secret_id="my-secret",
        secret=resources_pb2.Secret(labels={"env": "dev"}),
    )
    result = await svc.CreateSecret(req, FakeContext())
    assert result.name == "projects/p1/secrets/my-secret"
    assert dict(result.labels) == {"env": "dev"}


async def test_create_secret_already_exists():
    svc = servicer()
    req = service_pb2.CreateSecretRequest(
        parent="projects/p1", secret_id="x", secret=resources_pb2.Secret()
    )
    await svc.CreateSecret(req, FakeContext())
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.CreateSecret(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.ALREADY_EXISTS


async def test_create_secret_invalid_id():
    svc = servicer()
    req = service_pb2.CreateSecretRequest(
        parent="projects/p1", secret_id="bad/name", secret=resources_pb2.Secret()
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.CreateSecret(req, ctx)
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


async def test_get_secret_returns_labels_and_annotations():
    svc = servicer()
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent="projects/p1",
            secret_id="x",
            secret=resources_pb2.Secret(labels={"k": "v"}, annotations={"a": "b"}),
        ),
        FakeContext(),
    )
    result = await svc.GetSecret(
        service_pb2.GetSecretRequest(name="projects/p1/secrets/x"),
        FakeContext(),
    )
    assert result.name == "projects/p1/secrets/x"
    assert dict(result.labels) == {"k": "v"}
    assert dict(result.annotations) == {"a": "b"}


async def test_get_secret_not_found():
    svc = servicer()
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.GetSecret(
            service_pb2.GetSecretRequest(name="projects/p1/secrets/nope"),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


async def test_list_secrets():
    svc = servicer()
    for sid in ("b", "a"):
        await svc.CreateSecret(
            service_pb2.CreateSecretRequest(
                parent="projects/p1", secret_id=sid, secret=resources_pb2.Secret()
            ),
            FakeContext(),
        )
    result = await svc.ListSecrets(
        service_pb2.ListSecretsRequest(parent="projects/p1"),
        FakeContext(),
    )
    names = [s.name for s in result.secrets]
    assert names == [
        "projects/p1/secrets/a",
        "projects/p1/secrets/b",
    ]


async def test_update_secret_applies_mask():
    svc = servicer()
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent="projects/p1",
            secret_id="x",
            secret=resources_pb2.Secret(labels={"old": "true"}),
        ),
        FakeContext(),
    )
    req = service_pb2.UpdateSecretRequest(
        secret=resources_pb2.Secret(
            name="projects/p1/secrets/x",
            labels={"new": "true"},
            annotations={"ann": "1"},
        ),
        update_mask=FieldMask(paths=["labels"]),
    )
    result = await svc.UpdateSecret(req, FakeContext())
    assert dict(result.labels) == {"new": "true"}
    assert dict(result.annotations) == {}


async def test_delete_secret():
    svc = servicer()
    await svc.CreateSecret(
        service_pb2.CreateSecretRequest(
            parent="projects/p1", secret_id="x", secret=resources_pb2.Secret()
        ),
        FakeContext(),
    )
    await svc.DeleteSecret(
        service_pb2.DeleteSecretRequest(name="projects/p1/secrets/x"),
        FakeContext(),
    )
    ctx = FakeContext()
    with pytest.raises(grpc.aio.AioRpcError):
        await svc.GetSecret(
            service_pb2.GetSecretRequest(name="projects/p1/secrets/x"),
            ctx,
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND
