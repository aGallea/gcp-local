"""Unit tests for the BigQuery ui-api: table endpoints + preview."""

from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.names import duckdb_table_qualname


def _ds(dataset_id: str = "d") -> DatasetRecord:
    return DatasetRecord(
        project="p",
        dataset_id=dataset_id,
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={},
        location="US",
        default_table_expiration_ms=None,
    )


def _tbl(
    table_id: str = "t",
    schema: list[FieldSchema] | None = None,
) -> TableRecord:
    return TableRecord(
        project="p",
        dataset_id="d",
        table_id=table_id,
        schema=schema
        or [
            FieldSchema(name="id", type="INT64", mode="NULLABLE", fields=None),
            FieldSchema(name="name", type="STRING", mode="NULLABLE", fields=None),
        ],
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={},
        time_partitioning=None,
        range_partitioning=None,
        clustering=None,
    )


async def test_list_tables_for_dataset(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds())
    await svc.storage.create_table(_tbl("t1"))
    await svc.storage.create_table(_tbl("t2"))
    qual = duckdb_table_qualname("p", "d", "t1")
    await svc.storage.connection.execute(f"INSERT INTO {qual} VALUES (1, 'a'), (2, 'b')")
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects/p/datasets/d/tables")
    assert r.status_code == 200
    body = r.json()
    assert [t["table_id"] for t in body["tables"]] == ["t1", "t2"]
    assert body["tables"][0]["num_rows"] == 2
    assert body["tables"][1]["num_rows"] == 0


async def test_list_tables_missing_dataset(bq_ui_client) -> None:
    client, _ = bq_ui_client
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects/p/datasets/nope/tables")
    assert r.status_code == 404


async def test_get_table_returns_schema_and_row_count(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds())
    await svc.storage.create_table(_tbl("t"))
    qual = duckdb_table_qualname("p", "d", "t")
    await svc.storage.connection.execute(f"INSERT INTO {qual} VALUES (1, 'a'), (2, 'b')")
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects/p/datasets/d/tables/t")
    assert r.status_code == 200
    body = r.json()
    assert body["num_rows"] == 2
    assert [(f["name"], f["type"]) for f in body["table_schema"]] == [
        ("id", "INT64"),
        ("name", "STRING"),
    ]


async def test_get_table_missing_returns_404(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds())
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects/p/datasets/d/tables/missing")
    assert r.status_code == 404


async def test_delete_table_removes_it(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds())
    await svc.storage.create_table(_tbl("t"))
    r = await client.delete("/_emulator/ui-api/v1/bigquery/projects/p/datasets/d/tables/t")
    assert r.status_code == 204
    assert await svc.storage.list_tables("p", "d") == []


async def test_preview_returns_rows_and_paging(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds())
    await svc.storage.create_table(_tbl("t"))
    qual = duckdb_table_qualname("p", "d", "t")
    rows = ", ".join(f"({i}, 'r{i}')" for i in range(5))
    await svc.storage.connection.execute(f"INSERT INTO {qual} VALUES {rows}")
    r = await client.get(
        "/_emulator/ui-api/v1/bigquery/projects/p/datasets/d/tables/t/preview?max_results=2"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_rows"] == 5
    assert body["rows"] == [[0, "r0"], [1, "r1"]]
    assert body["next_offset"] == 2

    r2 = await client.get(
        "/_emulator/ui-api/v1/bigquery/projects/p/datasets/d/tables/t/preview?max_results=10&offset=2"
    )
    body2 = r2.json()
    assert body2["rows"] == [[2, "r2"], [3, "r3"], [4, "r4"]]
    assert body2["next_offset"] is None


async def test_preview_missing_table_returns_404(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await svc.storage.create_dataset(_ds())
    r = await client.get("/_emulator/ui-api/v1/bigquery/projects/p/datasets/d/tables/x/preview")
    assert r.status_code == 404
