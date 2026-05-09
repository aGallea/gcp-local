"""Unit tests for the BigQuery ui-api: dataset endpoints."""

from gcp_local.services.bigquery.models import DatasetRecord


def _ds(project: str = "p", dataset_id: str = "d", location: str = "US") -> DatasetRecord:
    return DatasetRecord(
        project=project,
        dataset_id=dataset_id,
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={},
        location=location,
        default_table_expiration_ms=None,
    )


async def test_list_projects_groups_by_project(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds(project="alpha", dataset_id="d1"))
    await svc.storage.create_dataset(_ds(project="alpha", dataset_id="d2"))
    await svc.storage.create_dataset(_ds(project="beta", dataset_id="x"))
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects")
    assert r.status_code == 200
    body = r.json()
    assert body["projects"] == [
        {"project": "alpha", "dataset_count": 2},
        {"project": "beta", "dataset_count": 1},
    ]


async def test_list_datasets_empty(bq_ui_client) -> None:
    client, _ = bq_ui_client
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects/p/datasets")
    assert r.status_code == 200
    assert r.json() == {"datasets": []}


async def test_list_datasets_returns_seeded(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds(dataset_id="alpha"))
    await svc.storage.create_dataset(_ds(dataset_id="beta", location="EU"))
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects/p/datasets")
    assert r.status_code == 200
    body = r.json()
    assert [d["dataset_id"] for d in body["datasets"]] == ["alpha", "beta"]
    assert body["datasets"][1]["location"] == "EU"


async def test_create_dataset_returns_summary(bq_ui_client) -> None:
    client, svc = bq_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/projects/p/datasets",
        json={"dataset_id": "newds", "location": "EU"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["dataset_id"] == "newds"
    assert body["location"] == "EU"
    got = await svc.storage.get_dataset("p", "newds")
    assert got.location == "EU"


async def test_create_dataset_conflict_returns_envelope(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds(dataset_id="dup"))
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/projects/p/datasets",
        json={"dataset_id": "dup"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "already_exists"


async def test_create_dataset_invalid_id_returns_400(bq_ui_client) -> None:
    client, _ = bq_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/projects/p/datasets",
        json={"dataset_id": ""},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_argument"


async def test_create_dataset_invalid_project_returns_400(bq_ui_client) -> None:
    client, _ = bq_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/projects/BadProject/datasets",
        json={"dataset_id": "ok"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_argument"


async def test_delete_dataset_succeeds_when_empty(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds(dataset_id="empty"))
    r = await client.delete("/_emulator/ui-api/v1/bigquery/projects/p/datasets/empty")
    assert r.status_code == 204
    assert await svc.storage.list_datasets("p") == []


async def test_delete_dataset_with_tables_requires_force(bq_ui_client) -> None:
    client, svc = bq_ui_client
    from gcp_local.services.bigquery.models import FieldSchema, TableRecord

    await svc.storage.create_dataset(_ds(dataset_id="d"))
    await svc.storage.create_table(
        TableRecord(
            project="p",
            dataset_id="d",
            table_id="t",
            schema=[FieldSchema(name="x", type="INT64", mode="NULLABLE", fields=None)],
            create_time="2026-04-25T00:00:00Z",
            last_modified_time="2026-04-25T00:00:00Z",
            description=None,
            labels={},
            time_partitioning=None,
            range_partitioning=None,
            clustering=None,
        )
    )
    r = await client.delete("/_emulator/ui-api/v1/bigquery/projects/p/datasets/d")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_empty"
    r = await client.delete(
        "/_emulator/ui-api/v1/bigquery/projects/p/datasets/d?delete_contents=true"
    )
    assert r.status_code == 204


async def test_delete_dataset_missing_returns_404(bq_ui_client) -> None:
    client, _ = bq_ui_client
    r = await client.delete("/_emulator/ui-api/v1/bigquery/projects/p/datasets/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
