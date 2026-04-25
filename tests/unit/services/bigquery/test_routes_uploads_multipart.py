"""Multipart upload handler (spec §3, §5.1)."""

from collections.abc import AsyncIterator

import json
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> AsyncIterator[TestClient]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    load_runner = LoadRunner(connection=conn, storage=storage)
    app = build_app(storage=storage, runner=runner, load_runner=load_runner)
    try:
        c = TestClient(app)
        c.post(
            "/bigquery/v2/projects/p/datasets",
            json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
        )
        yield c
    finally:
        await conn.shutdown()


def _multipart_body(
    metadata: dict, data: bytes, *, data_type: str = "application/octet-stream"
) -> tuple[bytes, str]:
    boundary = "===gcp_local_test_boundary==="
    md_bytes = json.dumps(metadata).encode("utf-8")
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + md_bytes + b"\r\n" + (
        f"--{boundary}\r\nContent-Type: {data_type}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    content_type = f"multipart/related; boundary={boundary}"
    return body, content_type


def test_multipart_load_table_from_json_happy_path(client: TestClient) -> None:
    metadata = {
        "jobReference": {"projectId": "p", "jobId": "load-1"},
        "configuration": {
            "load": {
                "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "u1"},
                "sourceFormat": "NEWLINE_DELIMITED_JSON",
                "schema": {
                    "fields": [
                        {"name": "id", "type": "INT64"},
                        {"name": "name", "type": "STRING"},
                    ]
                },
            }
        },
    }
    data = b'{"id": 1, "name": "alice"}\n{"id": 2, "name": "bob"}\n'
    body, content_type = _multipart_body(metadata, data)
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": content_type},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["jobReference"]["jobId"] == "load-1"
    assert job["configuration"]["jobType"] == "LOAD"
    assert job["statistics"]["load"]["outputRows"] == "2"
    # Job is queryable via jobs.get afterward.
    g = client.get("/bigquery/v2/projects/p/jobs/load-1")
    assert g.status_code == 200
    assert g.json()["jobReference"]["jobId"] == "load-1"


def test_multipart_unsupported_uploadtype(client: TestClient) -> None:
    body, ct = _multipart_body({}, b"")
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "media"},
        content=body,
        headers={"Content-Type": ct},
    )
    assert r.status_code == 400
    assert r.json()["error"]["errors"][0]["reason"] == "invalid"


def test_multipart_malformed_no_metadata_part(client: TestClient) -> None:
    boundary = "==b=="
    body = (
        f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n"
        f"raw\r\n--{boundary}--\r\n"
    ).encode()
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    assert r.status_code == 400


def test_multipart_load_failure_surfaces_as_job_with_errorResult(
    client: TestClient,
) -> None:
    metadata = {
        "jobReference": {"projectId": "p", "jobId": "load-bad"},
        "configuration": {
            "load": {
                "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "u_bad"},
                "sourceFormat": "PARQUET",
                "schema": {"fields": [{"name": "id", "type": "INT64"}]},
            }
        },
    }
    body, ct = _multipart_body(metadata, b"")
    r = client.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "multipart"},
        content=body,
        headers={"Content-Type": ct},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["status"]["errorResult"]["reason"] == "invalid"
    assert "PARQUET" in job["status"]["errorResult"]["message"]
