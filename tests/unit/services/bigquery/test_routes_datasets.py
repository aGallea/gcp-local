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
        yield TestClient(app)
    finally:
        await conn.shutdown()


def test_create_dataset_201(client: TestClient) -> None:
    r = client.post(
        "/bigquery/v2/projects/my-proj/datasets",
        json={
            "datasetReference": {"projectId": "my-proj", "datasetId": "my_ds"},
            "labels": {"env": "dev"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "bigquery#dataset"
    assert body["datasetReference"] == {"projectId": "my-proj", "datasetId": "my_ds"}
    assert body["labels"] == {"env": "dev"}


def test_get_dataset(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/my-proj/datasets",
        json={"datasetReference": {"projectId": "my-proj", "datasetId": "my_ds"}},
    )
    r = client.get("/bigquery/v2/projects/my-proj/datasets/my_ds")
    assert r.status_code == 200
    assert r.json()["datasetReference"]["datasetId"] == "my_ds"


def test_get_dataset_404(client: TestClient) -> None:
    r = client.get("/bigquery/v2/projects/my-proj/datasets/missing")
    assert r.status_code == 404
    assert r.json()["error"]["errors"][0]["reason"] == "notFound"


def test_create_duplicate_409(client: TestClient) -> None:
    body = {"datasetReference": {"projectId": "p", "datasetId": "d"}}
    client.post("/bigquery/v2/projects/p/datasets", json=body)
    r = client.post("/bigquery/v2/projects/p/datasets", json=body)
    assert r.status_code == 409


def test_list_datasets(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "a"}},
    )
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "b"}},
    )
    r = client.get("/bigquery/v2/projects/p/datasets")
    assert r.status_code == 200
    ids = [d["datasetReference"]["datasetId"] for d in r.json()["datasets"]]
    assert ids == ["a", "b"]


def test_delete_dataset(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    r = client.delete("/bigquery/v2/projects/p/datasets/d")
    assert r.status_code == 204
    r2 = client.get("/bigquery/v2/projects/p/datasets/d")
    assert r2.status_code == 404


def test_patch_dataset(client: TestClient) -> None:
    client.post(
        "/bigquery/v2/projects/p/datasets",
        json={"datasetReference": {"projectId": "p", "datasetId": "d"}},
    )
    r = client.patch(
        "/bigquery/v2/projects/p/datasets/d",
        json={"description": "hello", "labels": {"env": "dev"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "hello"
    assert body["labels"] == {"env": "dev"}
