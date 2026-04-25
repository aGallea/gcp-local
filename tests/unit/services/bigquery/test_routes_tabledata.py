from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def client() -> AsyncIterator[TestClient]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    app = build_app(storage=storage, runner=runner)
    try:
        c = TestClient(app)
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
        yield c
    finally:
        await conn.shutdown()


def test_insert_all_happy_path(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/t/insertAll",
        json={
            "rows": [
                {"insertId": "x1", "json": {"id": 1, "name": "a"}},
                {"insertId": "x2", "json": {"id": 2, "name": "b"}},
            ]
        },
    )
    assert r.status_code == 200
    assert r.json() == {"kind": "bigquery#tableDataInsertAllResponse"}

    q = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT count(*) AS c FROM `p.d.t`"},
    ).json()
    assert q["rows"][0]["f"][0]["v"] == "2"


def test_insert_all_table_not_found_404(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/missing/insertAll",
        json={"rows": [{"json": {"id": 1, "name": "a"}}]},
    )
    assert r.status_code == 404
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


def test_insert_all_per_row_errors_when_skip_invalid_false(
    client: TestClient,
) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/t/insertAll",
        json={
            "skipInvalidRows": False,
            "rows": [
                {"json": {"id": 1, "name": "a"}},
                {"json": {"name": "missing-id"}},  # missing REQUIRED field
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "insertErrors" in body
    assert body["insertErrors"][0]["index"] == 1


def test_insert_all_skip_invalid_inserts_valid_rows(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/t/insertAll",
        json={
            "skipInvalidRows": True,
            "rows": [
                {"json": {"id": 1, "name": "a"}},
                {"json": {"name": "missing-id"}},
            ],
        },
    )
    assert r.status_code == 200
    q = client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT count(*) AS c FROM `p.d.t`"},
    ).json()
    assert q["rows"][0]["f"][0]["v"] == "1"


@pytest.fixture
async def json_client() -> AsyncIterator[TestClient]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    runner = JobRunner(connection=conn, storage=storage)
    app = build_app(storage=storage, runner=runner)
    try:
        c = TestClient(app)
        c.post(
            "/bigquery/v2/projects/p/datasets",
            json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
        )
        c.post(
            "/bigquery/v2/projects/p/datasets/d/tables",
            json={
                "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "j"},
                "schema": {
                    "fields": [
                        {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                        {"name": "blob", "type": "JSON"},
                        {"name": "tags", "type": "JSON", "mode": "REPEATED"},
                    ]
                },
            },
        )
        yield c
    finally:
        await conn.shutdown()


def test_insert_all_json_column_accepts_native_dict_and_list(json_client: TestClient) -> None:
    # Regression: insertAll on a JSON column failed when the client sent a
    # native dict/list because DuckDB doesn't auto-convert those. We now
    # serialize on the server side so clients can send the natural shape.
    r = json_client.post(
        "/bigquery/v2/projects/p/datasets/d/tables/j/insertAll",
        json={
            "rows": [
                {
                    "json": {
                        "id": 1,
                        "blob": {"a": 1, "b": [2, 3]},
                        "tags": [{"k": "v1"}, {"k": "v2"}],
                    }
                }
            ]
        },
    )
    assert r.status_code == 200
    assert r.json() == {"kind": "bigquery#tableDataInsertAllResponse"}
    q = json_client.post(
        "/bigquery/v2/projects/p/queries",
        json={"query": "SELECT count(*) AS c FROM `p.d.j`"},
    ).json()
    assert q["rows"][0]["f"][0]["v"] == "1"
