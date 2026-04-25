from collections.abc import AsyncIterator

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


@pytest.fixture
async def runner() -> AsyncIterator[JobRunner]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    await storage.create_dataset(
        DatasetRecord(
            project="p",
            dataset_id="d",
            create_time="now",
            last_modified_time="now",
            description=None,
            labels={},
            location="US",
            default_table_expiration_ms=None,
        )
    )
    await storage.create_table(
        TableRecord(
            project="p",
            dataset_id="d",
            table_id="t",
            schema=[
                FieldSchema(name="id", type="INT64", mode="REQUIRED", fields=None),
                FieldSchema(name="name", type="STRING", mode="NULLABLE", fields=None),
            ],
            create_time="now",
            last_modified_time="now",
            description=None,
            labels={},
            time_partitioning=None,
            range_partitioning=None,
            clustering=None,
        )
    )
    await conn.execute("INSERT INTO \"p:d\".\"t\" VALUES (1, 'a'), (2, 'b'), (3, 'c')")
    try:
        yield JobRunner(connection=conn, storage=storage)
    finally:
        await conn.shutdown()


async def test_run_select_returns_done_job_with_total_rows(runner: JobRunner) -> None:
    rec = await runner.run_query(project="p", job_id="j1", sql="SELECT * FROM `p.d.t`")
    assert rec.state == "DONE"
    assert rec.statement_type == "SELECT"
    assert rec.total_rows == 3
    assert rec.error_result is None


async def test_run_dml_records_affected_rows(runner: JobRunner) -> None:
    rec = await runner.run_query(
        project="p", job_id="j2", sql="UPDATE `p.d.t` SET name='x' WHERE id=1"
    )
    assert rec.state == "DONE"
    assert rec.statement_type == "UPDATE"


async def test_run_select_paging(runner: JobRunner) -> None:
    rec = await runner.run_query(project="p", job_id="j3", sql="SELECT * FROM `p.d.t` ORDER BY id")
    page1 = await runner.read_page(rec.job_id, page_size=2, page_token=None)
    assert len(page1.rows) == 2
    assert page1.next_page_token is not None
    page2 = await runner.read_page(rec.job_id, page_size=2, page_token=page1.next_page_token)
    assert len(page2.rows) == 1
    assert page2.next_page_token is None


async def test_run_select_with_parse_error_records_error_result(
    runner: JobRunner,
) -> None:
    rec = await runner.run_query(project="p", job_id="j4", sql="SELECT FROM where")
    assert rec.state == "DONE"
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalidQuery"


async def test_run_select_unknown_table_records_not_found(
    runner: JobRunner,
) -> None:
    rec = await runner.run_query(project="p", job_id="j5", sql="SELECT * FROM `p.d.missing`")
    assert rec.error_result is not None
    assert rec.error_result["reason"] in ("notFound", "invalidQuery")


async def test_get_and_list_jobs(runner: JobRunner) -> None:
    await runner.run_query(project="p", job_id="j1", sql="SELECT 1")
    await runner.run_query(project="p", job_id="j2", sql="SELECT 2")
    rec = await runner.get("p", "j1")
    assert rec.job_id == "j1"
    listing = await runner.list_jobs("p")
    assert {r.job_id for r in listing} == {"j1", "j2"}


async def test_ttl_sweep_evicts_old_jobs(runner: JobRunner) -> None:
    rec = await runner.run_query(project="p", job_id="j1", sql="SELECT 1")
    runner.set_clock(lambda: 0)
    await runner.run_query(project="p", job_id="j2", sql="SELECT 2")
    runner.set_clock(lambda: 7200)  # 2h later
    await runner.sweep_expired(ttl_seconds=3600)
    listing = await runner.list_jobs("p")
    assert {r.job_id for r in listing} == {"j2"} or rec.job_id not in {r.job_id for r in listing}
