"""NDJSON load-job execution (spec §6.1, §9)."""

from collections.abc import AsyncIterator

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def runner() -> AsyncIterator[LoadRunner]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    # Pre-create dataset; the runner will create tables as needed.
    from gcp_local.services.bigquery.models import DatasetRecord

    await storage.create_dataset(
        DatasetRecord(
            project="p",
            dataset_id="d",
            create_time="0",
            last_modified_time="0",
            description=None,
            labels={},
            location="US",
            default_table_expiration_ms=None,
        )
    )
    yield LoadRunner(connection=conn, storage=storage)
    await conn.shutdown()


@pytest.mark.asyncio
async def test_ndjson_explicit_schema_create_if_needed(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "alice"}\n{"id": 2, "name": "bob"}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t1"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }
    rec = await runner.run_load(project="p", job_id="j1", load_config=config, data=body)
    assert rec.job_type == "LOAD"
    assert rec.error_result is None
    assert rec.total_rows == 2
    assert rec.load_stats["outputRows"] == "2"
    assert rec.load_stats["inputFileBytes"] == str(len(body))
    # Verify rows were actually inserted.
    rows = await runner._conn.execute('SELECT count(*) FROM "p:d"."t1"')
    assert rows[0][0] == 2


@pytest.mark.asyncio
async def test_ndjson_autodetect_creates_table(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "alice"}\n{"id": 2, "name": "bob"}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_auto"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "autodetect": True,
    }
    rec = await runner.run_load(project="p", job_id="j2", load_config=config, data=body)
    assert rec.error_result is None
    table = await runner._storage.get_table("p", "d", "t_auto")
    by_name = {f.name: f.type for f in table.schema}
    assert by_name == {"id": "INT64", "name": "STRING"}


@pytest.mark.asyncio
async def test_ndjson_create_never_missing_table(runner: LoadRunner) -> None:
    body = b'{"id": 1}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_missing"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "createDisposition": "CREATE_NEVER",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="j3", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "notFound"


@pytest.mark.asyncio
async def test_ndjson_unsupported_source_format(runner: LoadRunner) -> None:
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_pq"},
        "sourceFormat": "PARQUET",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="j4", load_config=config, data=b"")
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "PARQUET" in rec.error_result["message"]


@pytest.mark.asyncio
async def test_ndjson_parse_error_aborts_job(runner: LoadRunner) -> None:
    body = b'{"id": 1}\n{this is not json}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_bad"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {"fields": [{"name": "id", "type": "INT64"}]},
    }
    rec = await runner.run_load(project="p", job_id="j5", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "line 2" in rec.error_result["message"]


@pytest.mark.asyncio
async def test_ndjson_no_schema_no_autodetect_no_table_errors(runner: LoadRunner) -> None:
    body = b'{"id": 1}\n'
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_noschema"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
    }
    rec = await runner.run_load(project="p", job_id="j6", load_config=config, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "schema" in rec.error_result["message"].lower()
