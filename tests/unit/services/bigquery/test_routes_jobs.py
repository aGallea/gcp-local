from collections.abc import AsyncIterator

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
    c = TestClient(build_app(storage=storage, runner=runner, load_runner=load_runner))
    c.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    c.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                    {"name": "name", "type": "STRING"},
                ]
            },
        },
    )
    try:
        yield c
    finally:
        await conn.shutdown()


def _seed_rows(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "INSERT INTO `p.d.t` VALUES (1,'a'),(2,'b'),(3,'c')"},
    )


def test_jobs_query_synchronous(client: TestClient) -> None:
    _seed_rows(client)
    r = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT id, name FROM `p.d.t` ORDER BY id"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "bigquery#queryResponse"
    assert body["jobComplete"] is True
    assert body["totalRows"] == "3"
    rows = body["rows"]
    assert [row["f"][0]["v"] for row in rows] == ["1", "2", "3"]


def test_jobs_insert_async_shape(client: TestClient) -> None:
    _seed_rows(client)
    r = client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "j1"},
            "configuration": {"query": {"query": "SELECT id FROM `p.d.t`"}},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"]["state"] == "DONE"
    assert body["jobReference"] == {"projectId": "p", "jobId": "j1"}


def test_jobs_get_query_results_paging(client: TestClient) -> None:
    _seed_rows(client)
    r = client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "j2"},
            "configuration": {"query": {"query": "SELECT id FROM `p.d.t` ORDER BY id"}},
        },
    )
    assert r.status_code == 200
    page1 = client.get("/bigquery/v2/projects/p/queries/j2", params={"maxResults": 2}).json()
    assert len(page1["rows"]) == 2
    page2 = client.get(
        "/bigquery/v2/projects/p/queries/j2",
        params={"maxResults": 2, "pageToken": page1["pageToken"]},
    ).json()
    assert len(page2["rows"]) == 1


def test_jobs_get_query_results_max_results_zero_is_poll_only(
    client: TestClient,
) -> None:
    """Regression for issue #34.

    `getQueryResults?maxResults=0` is the BigQuery convention for "tell me
    the job state, don't return rows yet" used by python-bigquery during
    `QueryJob.result()` polling. The response must include schema and
    totalRows but neither `rows` nor `pageToken` — the client treats absence
    of `rows` as the signal that the empty page is *not* the first real page
    of results and re-fetches from scratch. Emitting `rows: []` together with
    a `pageToken` confuses the iterator and (when google-cloud-bigquery-
    storage is installed) pushes `to_dataframe()` onto the gRPC path the
    emulator doesn't implement, causing the client to hang in `select()`.
    """
    _seed_rows(client)
    client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "jZ"},
            "configuration": {"query": {"query": "SELECT id FROM `p.d.t` ORDER BY id"}},
        },
    )
    body = client.get("/bigquery/v2/projects/p/queries/jZ", params={"maxResults": 0}).json()
    assert body["jobComplete"] is True
    assert body["totalRows"] == "3"
    assert body["schema"]["fields"][0]["name"] == "id"
    assert "rows" not in body
    assert "pageToken" not in body


def test_jobs_query_parse_error_returns_error_result(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT FROM where"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["jobComplete"] is True
    assert body["errors"][0]["reason"] == "invalidQuery"


def test_jobs_get_query_results_on_dml_job_returns_empty_rows(
    client: TestClient,
) -> None:
    # DML jobs have no result table; getQueryResults must not 500.
    r = client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "dml1"},
            "configuration": {"query": {"query": "INSERT INTO `p.d.t` VALUES (99,'z')"}},
        },
    )
    assert r.status_code == 200
    assert r.json()["status"]["state"] == "DONE"

    r2 = client.get("/bigquery/v2/projects/p/queries/dml1")
    assert r2.status_code == 200
    body = r2.json()
    assert body["jobComplete"] is True
    assert body["rows"] == []
    assert body.get("schema", {}).get("fields") == []


def test_jobs_get_returns_known_job(client: TestClient) -> None:
    _seed_rows(client)
    client.post(
        "/bigquery/v2/projects/p/jobs",
        json={
            "jobReference": {"projectId": "p", "jobId": "jX"},
            "configuration": {"query": {"query": "SELECT 1"}},
        },
    )
    r = client.get("/bigquery/v2/projects/p/jobs/jX")
    assert r.status_code == 200
    assert r.json()["jobReference"]["jobId"] == "jX"
