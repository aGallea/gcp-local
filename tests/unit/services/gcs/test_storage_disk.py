import json
import os
import time
from pathlib import Path

import pytest

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord, UploadSession
from gcp_local.services.gcs.storage import (
    BucketNotFound,
    DiskStorage,
    ObjectCollision,
    SessionNotFound,
)


def make_record(bucket="b", name="o", size=5, gen=1, mgen=1) -> ObjectRecord:
    return ObjectRecord(
        bucket=bucket,
        name=name,
        size=size,
        generation=gen,
        metageneration=mgen,
        content_type="application/octet-stream",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )


async def test_create_bucket_writes_sidecar(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="mybucket", time_created="t"))
    meta_file = tmp_path / "mybucket" / "mybucket.meta.json"
    assert meta_file.exists()
    body = json.loads(meta_file.read_text())
    assert body["name"] == "mybucket"


async def test_put_object_writes_bytes_and_sidecar(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="dir/o.txt", size=5), b"hello")
    bytes_file = tmp_path / "b" / "objects" / "dir" / "o.txt"
    meta_file = tmp_path / "b" / "objects" / "dir" / "o.txt.meta.json"
    assert bytes_file.read_bytes() == b"hello"
    assert json.loads(meta_file.read_text())["name"] == "dir/o.txt"


async def test_object_with_trailing_slash_round_trips(tmp_path: Path):
    """Folder-placeholder objects (name ending in ``/``) are common in
    GCS-style UIs. The disk layout must not collide with the nested-directory
    scheme used for normal names."""
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    placeholder = make_record(name="logs/", size=0)
    await s.put_object(placeholder, b"")
    # Round-trip via get_object.
    got = await s.get_object("b", "logs/")
    assert got.name == "logs/"
    assert got.size == 0
    # Round-trip via list (logical name preserves the trailing slash).
    listed = await s.list_objects("b")
    assert [o.name for o in listed] == ["logs/"]
    # Bytes round-trip.
    assert await s.get_object_bytes("b", "logs/") == b""
    # And a real nested object inside the same prefix coexists with the
    # placeholder (they live at different on-disk paths).
    nested = make_record(name="logs/2026.log", size=3)
    await s.put_object(nested, b"abc")
    listed = await s.list_objects("b")
    assert sorted(o.name for o in listed) == ["logs/", "logs/2026.log"]
    # Delete removes only the placeholder.
    await s.delete_object("b", "logs/")
    listed = await s.list_objects("b")
    assert [o.name for o in listed] == ["logs/2026.log"]


async def test_collision_rule_object_vs_directory(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="foo"), b"x")
    with pytest.raises(ObjectCollision):
        # "foo" exists as a file; putting "foo/bar" needs "foo/" as a dir.
        await s.put_object(make_record(name="foo/bar"), b"y")


async def test_collision_rule_directory_vs_object(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="foo/bar"), b"x")
    with pytest.raises(ObjectCollision):
        # "foo/" exists as a dir; putting "foo" needs "foo" as a file.
        await s.put_object(make_record(name="foo"), b"y")


async def test_delete_bucket_removes_directory(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"x")
    await s.delete_bucket("b")
    assert not (tmp_path / "b").exists()


async def test_loads_state_from_existing_disk(tmp_path: Path):
    s1 = DiskStorage(tmp_path)
    await s1.create_bucket(BucketMeta(name="b", time_created="t"))
    await s1.put_object(make_record(name="o", size=3), b"abc")
    # New instance starts cold — should see the existing state
    s2 = DiskStorage(tmp_path)
    got = await s2.get_object("b", "o")
    assert got.name == "o"
    body = await s2.get_object_bytes("b", "o")
    assert body == b"abc"


async def test_session_persisted_to_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    sess = UploadSession(
        session_id="sess1",
        bucket="b",
        object_name="o",
        total_size=10,
        bytes_received=0,
        content_type="text/plain",
        user_metadata={},
        created_at="t",
        last_chunk_at="t",
    )
    await s.put_session(sess)
    await s.append_to_session("sess1", b"hello")
    # Fresh instance should still see the session
    s2 = DiskStorage(tmp_path)
    got = await s2.get_session("sess1")
    assert got.bytes_received == 5
    assert await s2.get_session_bytes("sess1") == b"hello"


async def test_session_gc_removes_stale(tmp_path: Path):
    """Sessions older than max_age_seconds are removed by gc_stale_sessions()."""
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    sess = UploadSession(
        session_id="old",
        bucket="b",
        object_name="o",
        total_size=10,
        bytes_received=0,
        content_type="text/plain",
        user_metadata={},
        created_at="t",
        last_chunk_at="t",
    )
    await s.put_session(sess)
    # Backdate the session dir's mtime by 8 days
    session_dir = tmp_path / "b" / ".uploads" / "old"
    assert session_dir.exists()
    ancient = time.time() - 8 * 86400
    os.utime(session_dir, (ancient, ancient))
    await s.gc_stale_sessions(max_age_seconds=7 * 86400)
    with pytest.raises(SessionNotFound):
        await s.get_session("old")


async def test_reset_wipes_disk(tmp_path: Path):
    s = DiskStorage(tmp_path)
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"x")
    await s.reset()
    with pytest.raises(BucketNotFound):
        await s.get_bucket("b")
    # Data dir is empty
    assert not any(tmp_path.iterdir())
