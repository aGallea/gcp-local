from pathlib import Path

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection


@pytest.mark.asyncio
async def test_in_memory_connection_bootstraps_catalog(tmp_path: Path) -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name IN ('_gcp_local_meta', '_gcp_local_jobs') "
        "ORDER BY schema_name"
    )
    assert [r[0] for r in rows] == ["_gcp_local_jobs", "_gcp_local_meta"]
    rows = await conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = '_gcp_local_meta' ORDER BY table_name"
    )
    assert [r[0] for r in rows] == ["datasets", "tables"]
    await conn.shutdown()


@pytest.mark.asyncio
async def test_disk_connection_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "bq.duckdb"
    conn = BigQueryConnection.on_disk(db_path)
    await conn.startup()
    await conn.execute("INSERT INTO _gcp_local_meta.datasets VALUES ('p', 'd', '{}')")
    await conn.shutdown()

    conn2 = BigQueryConnection.on_disk(db_path)
    await conn2.startup()
    rows = await conn2.execute("SELECT project, dataset_id FROM _gcp_local_meta.datasets")
    assert rows == [("p", "d")]
    await conn2.shutdown()


@pytest.mark.asyncio
async def test_reset_drops_user_schemas_keeps_catalog() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    await conn.execute('CREATE SCHEMA "p:d"')
    await conn.execute('CREATE TABLE "p:d"."t" (x BIGINT)')
    await conn.execute("INSERT INTO _gcp_local_meta.datasets VALUES ('p', 'd', '{}')")

    await conn.reset()

    rows = await conn.execute(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'p:d'"
    )
    assert rows == []
    rows = await conn.execute("SELECT count(*) FROM _gcp_local_meta.datasets")
    assert rows == [(0,)]
    await conn.shutdown()


@pytest.mark.asyncio
async def test_execute_runs_off_event_loop() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute("SELECT 1 + 1")
    assert rows == [(2,)]
    await conn.shutdown()
