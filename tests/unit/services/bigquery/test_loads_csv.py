"""CSV load-job execution (spec §6.2, §7.2)."""

from collections.abc import AsyncIterator

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.models import DatasetRecord
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def runner() -> AsyncIterator[LoadRunner]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    await storage.create_dataset(
        DatasetRecord(
            project="p", dataset_id="d", create_time="0", last_modified_time="0",
            description=None, labels={}, location="US", default_table_expiration_ms=None,
        )
    )
    yield LoadRunner(connection=conn, storage=storage)
    await conn.shutdown()


@pytest.mark.asyncio
async def test_csv_explicit_schema_skip_header(runner: LoadRunner) -> None:
    body = b"id,name\n1,alice\n2,bob\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_csv"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc1", load_config=config, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2
    rows = await runner._conn.execute('SELECT id, name FROM "p:d"."t_csv" ORDER BY id')
    assert [(r[0], r[1]) for r in rows] == [(1, "alice"), (2, "bob")]


@pytest.mark.asyncio
async def test_csv_autodetect_with_header(runner: LoadRunner) -> None:
    body = b"id,name\n1,alice\n2,bob\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_csv_auto"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "autodetect": True,
    }
    rec = await runner.run_load(project="p", job_id="jc2", load_config=config, data=body)
    assert rec.error_result is None
    table = await runner._storage.get_table("p", "d", "t_csv_auto")
    by_name = {f.name: f.type for f in table.schema}
    assert by_name == {"id": "INT64", "name": "STRING"}


@pytest.mark.asyncio
async def test_csv_custom_delimiter(runner: LoadRunner) -> None:
    body = b"id|name\n1|alice\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_pipe"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "fieldDelimiter": "|",
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc3", load_config=config, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 1


@pytest.mark.asyncio
async def test_csv_null_marker(runner: LoadRunner) -> None:
    body = b"id,name\n1,\\N\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_null"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "nullMarker": "\\N",
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc4", load_config=config, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT id, name FROM "p:d"."t_null"')
    assert rows[0][1] is None


@pytest.mark.asyncio
async def test_csv_no_header_synthesizes_columns(runner: LoadRunner) -> None:
    body = b"1,alice\n2,bob\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_noh"},
        "sourceFormat": "CSV",
        "autodetect": True,
    }
    rec = await runner.run_load(project="p", job_id="jc5", load_config=config, data=body)
    assert rec.error_result is None
    table = await runner._storage.get_table("p", "d", "t_noh")
    assert [f.name for f in table.schema] == ["string_field_0", "string_field_1"]


@pytest.mark.asyncio
async def test_csv_unsupported_encoding(runner: LoadRunner) -> None:
    body = b"id\n1\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_enc"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "encoding": "UTF-32",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="jc6", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "encoding" in rec.error_result["message"].lower()


@pytest.mark.asyncio
async def test_csv_column_count_mismatch(runner: LoadRunner) -> None:
    body = b"id,name\n1,alice,extra\n"
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_mismatch"},
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="jc7", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
