import json
from pathlib import Path

import pytest

from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersionState,
)
from gcp_local.services.secret_manager.storage import (
    DiskStorage,
    SecretNotFound,
)


def make_record(project="p", secret_id="s") -> SecretRecord:
    return SecretRecord(
        project=project,
        secret_id=secret_id,
        labels={},
        annotations={},
        create_time="t",
    )


async def test_create_writes_json_file(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="mine"))
    data_file = tmp_path / "secret_manager.json"
    assert data_file.exists()
    body = json.loads(data_file.read_text())
    assert body["secrets"][0]["secret_id"] == "mine"


async def test_roundtrip_through_disk(tmp_path: Path):
    s1 = DiskStorage(tmp_path)
    await s1.create_secret(make_record(secret_id="x"))
    await s1.add_version("p", "x", b"hello")
    s2 = DiskStorage(tmp_path)
    v = await s2.get_version("p", "x", 1)
    assert v.payload == b"hello"


async def test_version_payload_base64_on_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"\x00\x01\x02")
    body = json.loads((tmp_path / "secret_manager.json").read_text())
    v = body["secrets"][0]["versions"][0]
    assert "payload_b64" in v
    assert v["payload_b64"] == "AAEC"  # base64 of b"\x00\x01\x02"


async def test_destroy_clears_payload_on_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"secret")
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    body = json.loads((tmp_path / "secret_manager.json").read_text())
    v = body["secrets"][0]["versions"][0]
    assert v["state"] == "DESTROYED"
    assert v["payload_b64"] == ""


async def test_delete_secret_removes_from_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.delete_secret("p", "x")
    body = json.loads((tmp_path / "secret_manager.json").read_text())
    assert body["secrets"] == []


async def test_reset_wipes_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_secret(make_record(secret_id="x"))
    await s.reset()
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "x")


async def test_fresh_instance_on_empty_dir(tmp_path: Path):
    s = DiskStorage(tmp_path)
    items, _ = await s.list_secrets("p")
    assert items == []
