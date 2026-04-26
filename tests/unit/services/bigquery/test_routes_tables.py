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


def test_create_table(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                    {"name": "name", "type": "STRING"},
                ]
            },
            "labels": {"env": "dev"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "bigquery#table"
    assert body["tableReference"]["tableId"] == "t"
    assert [f["name"] for f in body["schema"]["fields"]] == ["id", "name"]


def test_get_table(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    r = client.get("/bigquery/v2/projects/p/datasets/d/tables/t")
    assert r.status_code == 200
    assert r.json()["tableReference"]["tableId"] == "t"


def test_list_tables(client: TestClient) -> None:
    for tid in ("a", "b"):
        client.post(
            "/bigquery/v2/projects/p/datasets/d/tables",
            json={
                "tableReference": {"projectId": "p", "datasetId": "d", "tableId": tid},
                "schema": {"fields": [{"name": "id", "type": "INT64"}]},
            },
        )
    r = client.get("/bigquery/v2/projects/p/datasets/d/tables")
    assert r.status_code == 200
    ids = [t["tableReference"]["tableId"] for t in r.json()["tables"]]
    assert ids == ["a", "b"]


def test_create_rejects_geography(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "g"},
            "schema": {"fields": [{"name": "loc", "type": "GEOGRAPHY"}]},
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["errors"][0]["reason"] == "invalid"


def test_delete_table(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    r = client.delete("/bigquery/v2/projects/p/datasets/d/tables/t")
    assert r.status_code == 204
    assert client.get("/bigquery/v2/projects/p/datasets/d/tables/t").status_code == 404


def test_patch_table(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets/d/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    r = client.patch(
        "/bigquery/v2/projects/p/datasets/d/tables/t",
        json={"description": "hi", "labels": {"a": "b"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "hi"
    assert body["labels"] == {"a": "b"}


def test_create_in_missing_dataset_404(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/p/datasets/missing/tables",
        json={
            "tableReference": {"projectId": "p", "datasetId": "missing", "tableId": "t"},
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        },
    )
    assert r.status_code == 404
