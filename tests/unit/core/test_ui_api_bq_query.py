"""Unit tests for the BigQuery ui-api: ad-hoc query endpoint."""

from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.names import duckdb_table_qualname


async def _seed(svc) -> None:
    await svc.storage.create_dataset(
        DatasetRecord(
            project="p",
            dataset_id="d",
            create_time="2026-04-25T00:00:00Z",
            last_modified_time="2026-04-25T00:00:00Z",
            description=None,
            labels={},
            location="US",
            default_table_expiration_ms=None,
        )
    )
    await svc.storage.create_table(
        TableRecord(
            project="p",
            dataset_id="d",
            table_id="t",
            schema=[
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
    )
    qual = duckdb_table_qualname("p", "d", "t")
    await svc.storage.connection.execute(f"INSERT INTO {qual} VALUES (1, 'a'), (2, 'b'), (3, 'c')")


async def test_query_select_returns_rows(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await _seed(svc)
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/queries",
        json={
            "project": "p",
            "sql": "SELECT id, name FROM `p.d.t` ORDER BY id",
            "max_results": 10,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["statement_type"] == "SELECT"
    assert body["total_rows"] == 3
    assert body["rows"] == [[1, "a"], [2, "b"], [3, "c"]]
    assert [f["name"] for f in body["table_schema"]] == ["id", "name"]


async def test_query_invalid_sql_returns_error_envelope(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await _seed(svc)
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/queries",
        json={"project": "p", "sql": "SELECT * FROM `p.d.unknown`", "max_results": 10},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert body["rows"] == []


async def test_query_empty_sql_returns_400(bq_ui_client) -> None:
    client, _ = bq_ui_client
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/queries",
        json={"project": "p", "sql": "   ", "max_results": 10},
    )
    assert r.status_code == 400


async def test_query_dml_returns_no_rows(bq_ui_client) -> None:
    client, svc = bq_ui_client
    await _seed(svc)
    r = await client.post(
        "/_emulator/ui-api/v1/bigquery/queries",
        json={
            "project": "p",
            "sql": "INSERT INTO `p.d.t` (id, name) VALUES (4, 'd')",
            "max_results": 10,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["statement_type"] == "INSERT"
    assert body["rows"] == []
