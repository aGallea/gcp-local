import asyncio
import socket
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


async def test_start_uses_pre_bound_socket_port(tmp_path: Path) -> None:
    """When ctx.sockets["gcs"] is provided the service binds to that socket's port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))
    port = s.getsockname()[1]

    svc = GcsService()
    ctx = Context(persist=False, data_dir=tmp_path, sockets={"gcs": s})
    await svc.start(ctx)
    try:
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            pytest.fail(f"GCS service did not come up on pre-bound port {port}")
    finally:
        await svc.stop()


async def test_start_without_socket_falls_back_to_port_override(tmp_path: Path) -> None:
    """Without ctx.sockets the service uses port_overrides as before."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))
    port = s.getsockname()[1]
    s.close()

    svc = GcsService()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"gcs": port})
    await svc.start(ctx)
    try:
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            pytest.fail(f"GCS service did not come up on port {port}")
    finally:
        await svc.stop()
