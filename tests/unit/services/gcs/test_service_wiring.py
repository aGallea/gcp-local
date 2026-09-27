from pathlib import Path

import pytest

from gcp_local.core.context import Context
from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.models import BucketMeta
from gcp_local.services.gcs.service import GcsService
from gcp_local.services.gcs.storage import DiskStorage, InMemoryStorage


@pytest.fixture
def ctx_memory(tmp_path: Path) -> Context:
    return Context(persist=False, data_dir=tmp_path, state_hub=StateHub())


@pytest.fixture
def ctx_disk(tmp_path: Path) -> Context:
    return Context(persist=True, data_dir=tmp_path, state_hub=StateHub())


def test_memory_backend_selected_when_no_persist(ctx_memory: Context) -> None:
    svc = GcsService()
    storage = svc._make_storage(ctx_memory)
    assert isinstance(storage, InMemoryStorage)


def test_disk_backend_selected_when_persist(ctx_disk: Context, tmp_path: Path) -> None:
    svc = GcsService()
    storage = svc._make_storage(ctx_disk)
    assert isinstance(storage, DiskStorage)
    assert (tmp_path / "gcs").is_dir()


async def test_disk_storage_reused_across_starts(ctx_disk: Context) -> None:
    svc = GcsService()
    storage = svc._make_storage(ctx_disk)
    assert isinstance(storage, DiskStorage)
    await storage.create_bucket(BucketMeta(name="persisted", time_created="t"))

    svc2 = GcsService()
    storage2 = svc2._make_storage(ctx_disk)
    buckets = await storage2.list_buckets()
    assert [b.name for b in buckets] == ["persisted"]


async def test_storage_property_exposed_after_start(tmp_path):
    from gcp_local.core.context import Context
    from gcp_local.services.gcs import GcsService

    svc = GcsService()
    ctx = Context(persist=False, data_dir=tmp_path)
    await svc.start(ctx)
    try:
        assert svc.storage is not None
        # Sanity: callable behaves like a GcsStorage.
        buckets = await svc.storage.list_buckets()
        assert buckets == []
    finally:
        await svc.stop()


def test_storage_property_raises_before_start():
    from gcp_local.services.gcs import GcsService

    svc = GcsService()
    import pytest

    with pytest.raises(RuntimeError, match="not started"):
        _ = svc.storage


def test_gcs_declares_a_rest_port_and_a_named_grpc_port() -> None:
    from gcp_local.core.service import Port

    assert GcsService.default_ports == [Port(4443, "rest"), Port(4444, "grpc", name="grpc")]


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_grpc_port_serves_the_same_storage_as_rest(tmp_path: Path) -> None:
    import grpc

    from gcp_local.generated.google.storage.v2 import storage_pb2, storage_pb2_grpc

    rest_port, grpc_port = _free_port(), _free_port()
    svc = GcsService()
    ctx = Context(
        persist=False,
        data_dir=tmp_path,
        port_overrides={"gcs": rest_port, "gcs_grpc": grpc_port},
        state_hub=StateHub(),
    )
    await svc.start(ctx)
    try:
        await svc.storage.create_bucket(BucketMeta(name="shared", time_created="t"))
        async with grpc.aio.insecure_channel(f"127.0.0.1:{grpc_port}") as channel:
            stub = storage_pb2_grpc.StorageStub(channel)
            resp = await stub.ListObjects(
                storage_pb2.ListObjectsRequest(parent="projects/_/buckets/shared")
            )
        assert list(resp.objects) == []
    finally:
        await svc.stop()
