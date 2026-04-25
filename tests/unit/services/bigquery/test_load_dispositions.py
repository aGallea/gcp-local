"""Write/create-disposition matrix for load jobs (spec §8)."""

from collections.abc import AsyncIterator

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


SCHEMA_FIELDS = [{"name": "id", "type": "INT64"}]


async def _seed_table(storage: BigQueryStorage, table_id: str) -> None:
    await storage.create_table(
        TableRecord(
            project="p",
            dataset_id="d",
            table_id=table_id,
            schema=[FieldSchema(name="id", type="INT64", mode="NULLABLE", fields=None)],
            create_time="0",
            last_modified_time="0",
            description=None,
            labels={},
            time_partitioning=None,
            range_partitioning=None,
            clustering=None,
        )
    )


async def _row_count(conn, table_id: str) -> int:
    rows = await conn.execute(f'SELECT count(*) FROM "p:d"."{table_id}"')
    return int(rows[0][0])


async def _insert_one(conn, table_id: str, value: int) -> None:
    await conn.execute(f'INSERT INTO "p:d"."{table_id}" VALUES (?)', [value])


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
async def test_write_append_default(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_app")
    await _insert_one(runner._conn, "t_app", 99)
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_app"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_app", load_config=config, data=b'{"id": 1}\n{"id": 2}\n'
    )
    assert rec.error_result is None
    assert await _row_count(runner._conn, "t_app") == 3


@pytest.mark.asyncio
async def test_write_truncate(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_trunc")
    for v in (10, 20, 30):
        await _insert_one(runner._conn, "t_trunc", v)
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_trunc"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "writeDisposition": "WRITE_TRUNCATE",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_tr", load_config=config, data=b'{"id": 1}\n'
    )
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT id FROM "p:d"."t_trunc" ORDER BY id')
    assert [r[0] for r in rows] == [1]


@pytest.mark.asyncio
async def test_write_empty_against_non_empty_fails(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_we")
    await _insert_one(runner._conn, "t_we", 7)
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_we"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "writeDisposition": "WRITE_EMPTY",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_we", load_config=config, data=b'{"id": 1}\n'
    )
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "duplicate"
    # Original row remains.
    assert await _row_count(runner._conn, "t_we") == 1


@pytest.mark.asyncio
async def test_write_empty_against_empty_succeeds(runner: LoadRunner) -> None:
    await _seed_table(runner._storage, "t_we_ok")
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_we_ok"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "writeDisposition": "WRITE_EMPTY",
        "schema": {"fields": SCHEMA_FIELDS},
    }
    rec = await runner.run_load(
        project="p", job_id="j_we2", load_config=config, data=b'{"id": 1}\n'
    )
    assert rec.error_result is None
    assert await _row_count(runner._conn, "t_we_ok") == 1


@pytest.mark.asyncio
async def test_create_if_needed_uses_existing_table_schema(runner: LoadRunner) -> None:
    """No explicit schema, no autodetect, but the table exists → use it."""
    await _seed_table(runner._storage, "t_existing")
    config = {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_existing"},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
    }
    rec = await runner.run_load(
        project="p", job_id="j_e", load_config=config, data=b'{"id": 5}\n'
    )
    assert rec.error_result is None
    assert await _row_count(runner._conn, "t_existing") == 1
