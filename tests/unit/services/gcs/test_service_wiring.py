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
