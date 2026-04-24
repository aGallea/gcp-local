import pytest

from gcp_local.services.gcs.models import BucketMeta, ObjectRecord, UploadSession
from gcp_local.services.gcs.storage import (
    BucketAlreadyExists,
    BucketNotFound,
    InMemoryStorage,
    ObjectNotFound,
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


async def test_create_and_get_bucket():
    s = InMemoryStorage()
    b = BucketMeta(name="my-bucket", time_created="t")
    await s.create_bucket(b)
    assert (await s.get_bucket("my-bucket")).name == "my-bucket"


async def test_create_existing_bucket_raises():
    s = InMemoryStorage()
    b = BucketMeta(name="my-bucket", time_created="t")
    await s.create_bucket(b)
    with pytest.raises(BucketAlreadyExists):
        await s.create_bucket(b)


async def test_get_missing_bucket_raises():
    s = InMemoryStorage()
    with pytest.raises(BucketNotFound):
        await s.get_bucket("nope")


async def test_list_buckets_sorted():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.create_bucket(BucketMeta(name="a", time_created="t"))
    assert [b.name for b in await s.list_buckets()] == ["a", "b"]


async def test_delete_bucket_happy():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="a", time_created="t"))
    await s.delete_bucket("a")
    with pytest.raises(BucketNotFound):
        await s.get_bucket("a")


async def test_delete_missing_bucket_raises():
    s = InMemoryStorage()
    with pytest.raises(BucketNotFound):
        await s.delete_bucket("a")


async def test_put_and_get_object():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    rec = make_record(name="logs/a.log")
    await s.put_object(rec, b"hello")
    got = await s.get_object("b", "logs/a.log")
    assert got.name == "logs/a.log"
    body = await s.get_object_bytes("b", "logs/a.log")
    assert body == b"hello"


async def test_get_missing_object_raises():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    with pytest.raises(ObjectNotFound):
        await s.get_object("b", "nope")


async def test_list_objects_prefix():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    for n in ("a", "logs/1", "logs/2", "z"):
        await s.put_object(make_record(name=n), b"")
    names = [o.name for o in await s.list_objects("b", prefix="logs/", delimiter=None)]
    assert names == ["logs/1", "logs/2"]


async def test_list_objects_delimiter_returns_prefixes():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    for n in ("a.log", "logs/1", "logs/2", "other/x"):
        await s.put_object(make_record(name=n), b"")
    objects, prefixes = await s.list_objects_with_prefixes("b", prefix="", delimiter="/")
    assert {o.name for o in objects} == {"a.log"}
    assert set(prefixes) == {"logs/", "other/"}


async def test_list_objects_pagination():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    for i in range(10):
        await s.put_object(make_record(name=f"n{i:02d}"), b"")
    page1 = await s.list_objects("b", prefix="", delimiter=None, max_results=3)
    assert [o.name for o in page1] == ["n00", "n01", "n02"]
    page2 = await s.list_objects("b", prefix="", delimiter=None, max_results=3, start_after="n02")
    assert [o.name for o in page2] == ["n03", "n04", "n05"]


async def test_delete_object_happy():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"")
    await s.delete_object("b", "o")
    with pytest.raises(ObjectNotFound):
        await s.get_object("b", "o")


async def test_delete_missing_object_raises():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    with pytest.raises(ObjectNotFound):
        await s.delete_object("b", "o")


async def test_overwrite_object_increases_generation():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o", gen=1), b"a")
    await s.put_object(make_record(name="o", gen=2), b"bb")
    got = await s.get_object("b", "o")
    assert got.generation == 2
    body = await s.get_object_bytes("b", "o")
    assert body == b"bb"


async def test_object_collision_rules_flat_mode():
    # InMemoryStorage does not collide (filesystem rule only applies to DiskStorage).
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="foo"), b"x")
    await s.put_object(make_record(name="foo/bar"), b"y")  # no collision in memory
    got_foo = await s.get_object("b", "foo")
    got_foobar = await s.get_object("b", "foo/bar")
    assert got_foo.name == "foo" and got_foobar.name == "foo/bar"


async def test_session_lifecycle():
    s = InMemoryStorage()
    sess = UploadSession(
        session_id="abc",
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
    got = await s.get_session("abc")
    assert got.session_id == "abc"
    await s.append_to_session("abc", b"hello")
    got = await s.get_session("abc")
    assert got.bytes_received == 5
    await s.delete_session("abc")
    with pytest.raises(SessionNotFound):
        await s.get_session("abc")


async def test_session_buffer_accumulates():
    s = InMemoryStorage()
    sess = UploadSession(
        session_id="s",
        bucket="b",
        object_name="o",
        total_size=None,
        bytes_received=0,
        content_type="t",
        user_metadata={},
        created_at="t",
        last_chunk_at="t",
    )
    await s.put_session(sess)
    await s.append_to_session("s", b"ab")
    await s.append_to_session("s", b"cd")
    buf = await s.get_session_bytes("s")
    assert buf == b"abcd"


async def test_reset_wipes_everything():
    s = InMemoryStorage()
    await s.create_bucket(BucketMeta(name="b", time_created="t"))
    await s.put_object(make_record(name="o"), b"x")
    await s.put_session(
        UploadSession(
            session_id="s",
            bucket="b",
            object_name="o",
            total_size=None,
            bytes_received=0,
            content_type="t",
            user_metadata={},
            created_at="t",
            last_chunk_at="t",
        )
    )
    await s.reset()
    with pytest.raises(BucketNotFound):
        await s.get_bucket("b")
    with pytest.raises(SessionNotFound):
        await s.get_session("s")
