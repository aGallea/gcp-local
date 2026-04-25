"""Resumable upload route handler (spec §5.2)."""

from collections.abc import AsyncIterator

import json
import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.engine.resumable import ResumableSessionStore
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> AsyncIterator[tuple[TestClient, ResumableSessionStore]]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    load_runner = LoadRunner(connection=conn, storage=storage)
    sessions = ResumableSessionStore()
    app = build_app(
        storage=storage, runner=runner, load_runner=load_runner, resumables=sessions,
    )
    try:
        c = TestClient(app)
        c.post(
            "/bigquery/v2/projects/p/datasets",
            json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
        )
        yield c, sessions
    finally:
        await conn.shutdown()


def _init_metadata(table: str = "rt") -> dict:
    return {
        "jobReference": {"projectId": "p", "jobId": f"load-{table}"},
        "configuration": {
            "load": {
                "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": table},
                "sourceFormat": "NEWLINE_DELIMITED_JSON",
                "schema": {"fields": [{"name": "id", "type": "INT64"}]},
            }
        },
    }


def test_resumable_init_returns_location(client) -> None:
    c, _ = client
    md = _init_metadata()
    r = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json", "X-Upload-Content-Length": "20"},
    )
    assert r.status_code == 200
    loc = r.headers.get("Location")
    assert loc is not None
    assert "upload_id=" in loc


def test_resumable_full_upload_completes(client) -> None:
    c, _ = client
    md = _init_metadata("rt2")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    payload = b'{"id": 1}\n{"id": 2}\n'
    r = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=payload,
        headers={"Content-Range": f"bytes 0-{len(payload) - 1}/{len(payload)}"},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["statistics"]["load"]["outputRows"] == "2"


def test_resumable_chunked_upload(client) -> None:
    c, _ = client
    md = _init_metadata("rt3")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    body = b'{"id": 1}\n{"id": 2}\n{"id": 3}\n'
    mid = len(body) // 2
    r1 = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=body[:mid],
        headers={"Content-Range": f"bytes 0-{mid - 1}/{len(body)}"},
    )
    assert r1.status_code == 308
    r2 = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=body[mid:],
        headers={"Content-Range": f"bytes {mid}-{len(body) - 1}/{len(body)}"},
    )
    assert r2.status_code == 200
    job = r2.json()
    assert job["statistics"]["load"]["outputRows"] == "3"


def test_resumable_unknown_session(client) -> None:
    c, _ = client
    r = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": "nope"},
        content=b"x",
        headers={"Content-Range": "bytes 0-0/1"},
    )
    assert r.status_code == 410
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


def test_resumable_out_of_order_chunk(client) -> None:
    c, _ = client
    md = _init_metadata("rt4")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    r = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=b"abc",
        headers={"Content-Range": "bytes 5-7/10"},
    )
    assert r.status_code == 400


def test_resumable_delete_drops_session(client) -> None:
    c, sessions = client
    md = _init_metadata("rt5")
    init = c.post(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"uploadType": "resumable"},
        content=json.dumps(md).encode(),
        headers={"Content-Type": "application/json"},
    )
    upload_id = init.headers["Location"].split("upload_id=")[1]
    r = c.delete(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
    )
    assert r.status_code == 200
    # Subsequent PUT should now 410.
    r2 = c.put(
        "/upload/bigquery/v2/projects/p/jobs",
        params={"upload_id": upload_id},
        content=b"x",
        headers={"Content-Range": "bytes 0-0/1"},
    )
    assert r2.status_code == 410
