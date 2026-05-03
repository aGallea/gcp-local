"""Regression tests for GCS JSON-API integer-as-string serialization.

Per the Google Cloud Storage JSON API spec, several fields on Object and
Bucket resources are typed as int64/uint64 in the underlying schema but
MUST be wire-serialized as JSON-quoted strings. The auto-generated Go
client (``google.golang.org/api/storage/v1/storage-gen.go``) declares them
with ``json:",string"`` tags, which causes its unmarshaller to reject raw
JSON numbers — Argo Workflows' executor hits this on uploads.

Affected fields:
- Object: ``size``, ``generation``, ``metageneration`` (and the same names
  inside ``items[]`` for list endpoints).
- Bucket: ``metageneration``.

This module asserts that every endpoint that returns one of these resources
emits the relevant fields as JSON strings, not as JSON numbers.
"""

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.models import BucketMeta, ObjectRecord
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import InMemoryStorage


def _rec(name: str = "hello.txt", *, gen: int = 1, size: int = 5) -> ObjectRecord:
    return ObjectRecord(
        bucket="b",
        name=name,
        size=size,
        generation=gen,
        metageneration=1,
        content_type="text/plain",
        md5_hash="",
        crc32c="",
        time_created="t",
        updated="t",
    )


@pytest.fixture
async def client():
    storage = InMemoryStorage()
    await storage.create_bucket(BucketMeta(name="b", time_created="t"))
    await storage.put_object(_rec("hello.txt"), b"hello")
    app = FastAPI()
    app.include_router(
        build_router(storage=storage, state_hub=StateHub(), generations=GenerationCounter())
    )
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://emulator:9023")


def _raw_value(text: str, key: str) -> str:
    """Return the raw substring after ``"<key>":`` in JSON text.

    Used to assert the wire-format type (string vs number) directly,
    independent of how ``r.json()`` re-parses it.
    """
    needle = f'"{key}":'
    idx = text.find(needle)
    assert idx != -1, f"key {key!r} not found in body: {text}"
    after = text[idx + len(needle) :].lstrip()
    end = len(after)
    for terminator in ",}\n":
        i = after.find(terminator)
        if i != -1 and i < end:
            end = i
    return after[:end].strip()


# ---- Object endpoints ------------------------------------------------------


async def test_get_object_emits_int_fields_as_strings(client):
    r = await client.get("/storage/v1/b/b/o/hello.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["size"] == "5"
    assert body["generation"] == "1"
    assert body["metageneration"] == "1"
    # Belt-and-suspenders: the raw JSON has them quoted, not as numbers.
    assert _raw_value(r.text, "size") == '"5"'
    assert _raw_value(r.text, "generation") == '"1"'
    assert _raw_value(r.text, "metageneration") == '"1"'


async def test_list_objects_items_emit_int_fields_as_strings(client):
    r = await client.get("/storage/v1/b/b/o")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) >= 1
    for item in body["items"]:
        assert isinstance(item["size"], str)
        assert isinstance(item["generation"], str)
        assert isinstance(item["metageneration"], str)
        # Sanity: they parse back to ints.
        int(item["size"])
        int(item["generation"])
        int(item["metageneration"])


async def test_upload_media_emits_int_fields_as_strings(client):
    r = await client.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "media", "name": "uploaded.txt"},
        content=b"hello world",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["size"] == "11"
    assert body["generation"] == str(int(body["generation"]))  # is string-shaped
    assert body["metageneration"] == "1"
    assert isinstance(body["size"], str)
    assert isinstance(body["generation"], str)
    assert isinstance(body["metageneration"], str)
    assert _raw_value(r.text, "size") == '"11"'


async def test_upload_multipart_emits_int_fields_as_strings(client):
    boundary = "----foo"
    body_bytes = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        '{"name":"mp.txt"}\r\n'
        f"--{boundary}\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "hi from multipart\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    r = await client.post(
        "/upload/storage/v1/b/b/o",
        params={"uploadType": "multipart"},
        content=body_bytes,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["size"], str)
    assert isinstance(body["generation"], str)
    assert isinstance(body["metageneration"], str)
    assert body["size"] == "17"


async def test_patch_object_emits_int_fields_as_strings(client):
    r = await client.patch(
        "/storage/v1/b/b/o/hello.txt",
        json={"contentType": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["size"], str)
    assert isinstance(body["generation"], str)
    assert isinstance(body["metageneration"], str)


# ---- Bucket endpoints ------------------------------------------------------


async def test_get_bucket_emits_metageneration_as_string(client):
    r = await client.get("/storage/v1/b/b")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["metageneration"], str)
    assert body["metageneration"] == "1"
    assert _raw_value(r.text, "metageneration") == '"1"'


async def test_list_buckets_items_emit_metageneration_as_string(client):
    r = await client.get("/storage/v1/b")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) >= 1
    for item in body["items"]:
        assert isinstance(item["metageneration"], str)


async def test_create_bucket_emits_metageneration_as_string(client):
    r = await client.post(
        "/storage/v1/b",
        params={"project": "demo"},
        json={"name": "fresh"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["metageneration"], str)
    assert body["metageneration"] == "1"


# ---- Round-trip (serialize → deserialize) ----------------------------------


def test_object_record_roundtrip_string_to_int():
    """Persisted JSON contains string-typed fields; re-loading must parse to int."""
    rec = _rec(size=42, gen=7)
    text = rec.model_dump_json()
    payload = json.loads(text)
    assert payload["size"] == "42"
    assert payload["generation"] == "7"
    assert payload["metageneration"] == "1"
    parsed = ObjectRecord.model_validate_json(text)
    assert parsed.size == 42
    assert parsed.generation == 7
    assert parsed.metageneration == 1


def test_bucket_meta_roundtrip_string_to_int():
    bucket = BucketMeta(name="x", time_created="t", metageneration=3)
    text = bucket.model_dump_json()
    payload = json.loads(text)
    assert payload["metageneration"] == "3"
    parsed = BucketMeta.model_validate_json(text)
    assert parsed.metageneration == 3
