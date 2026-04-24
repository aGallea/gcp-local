from gcp_local.services.gcs.models import (
    BucketMeta,
    ObjectRecord,
    UploadSession,
)


def test_bucket_meta_defaults():
    b = BucketMeta(name="my-bucket", time_created="2026-04-24T00:00:00Z")
    assert b.name == "my-bucket"
    assert b.metageneration == 1
    assert b.location == "US"
    assert b.storage_class == "STANDARD"


def test_object_record_defaults():
    o = ObjectRecord(
        bucket="b",
        name="o",
        size=0,
        generation=1,
        metageneration=1,
        content_type="application/octet-stream",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )
    assert o.metadata == {}
    assert o.content_encoding == ""
    assert o.cache_control == ""


def test_object_record_etag_computed():
    o = ObjectRecord(
        bucket="b",
        name="o",
        size=0,
        generation=42,
        metageneration=3,
        content_type="application/octet-stream",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )
    assert o.etag == '"42/3"'


def test_upload_session_fields():
    s = UploadSession(
        session_id="abc",
        bucket="b",
        object_name="o",
        total_size=1000,
        bytes_received=500,
        content_type="text/plain",
        user_metadata={"k": "v"},
        created_at="t",
        last_chunk_at="t",
    )
    assert s.is_complete is False


def test_upload_session_complete():
    s = UploadSession(
        session_id="abc",
        bucket="b",
        object_name="o",
        total_size=1000,
        bytes_received=1000,
        content_type="text/plain",
        user_metadata={},
        created_at="t",
        last_chunk_at="t",
    )
    assert s.is_complete is True


def test_upload_session_unknown_total():
    s = UploadSession(
        session_id="abc",
        bucket="b",
        object_name="o",
        total_size=None,
        bytes_received=500,
        content_type="text/plain",
        user_metadata={},
        created_at="t",
        last_chunk_at="t",
    )
    assert s.is_complete is False
