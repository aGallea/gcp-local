"""maxBadRecords + ignoreUnknownValues semantics for load jobs."""

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


def _ndjson_config(table: str) -> dict:
    return {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": table},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }


def _csv_config(table: str, *, skip: int = 1) -> dict:
    return {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": table},
        "sourceFormat": "CSV",
        "skipLeadingRows": skip,
        "schema": {
            "fields": [
                {"name": "id", "type": "INT64", "mode": "REQUIRED"},
                {"name": "name", "type": "STRING"},
            ]
        },
    }


# ---------- Default behavior (no flags) ------------------------------------


@pytest.mark.asyncio
async def test_default_one_bad_row_fails_the_job(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "ok"}\n{"name": "no_id"}\n'
    rec = await runner.run_load(
        project="p", job_id="j", load_config=_ndjson_config("t_def"), data=body
    )
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "Too many errors" in rec.error_result["message"]


# ---------- maxBadRecords --------------------------------------------------


@pytest.mark.asyncio
async def test_max_bad_records_under_threshold_succeeds(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "ok"}\n{"name": "missing_id"}\n{"id": 2, "name": "also_ok"}\n'
    cfg = _ndjson_config("t_under") | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j2", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2  # only the good rows
    assert rec.load_stats["badRecords"] == "1"
    assert rec.load_stats["outputRows"] == "2"


@pytest.mark.asyncio
async def test_max_bad_records_exact_match_succeeds(runner: LoadRunner) -> None:
    """Threshold is inclusive: bad_count == maxBadRecords still succeeds."""
    body = b'{"id": 1, "name": "ok"}\n{"name": "bad"}\n'
    cfg = _ndjson_config("t_eq") | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j3", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.load_stats["badRecords"] == "1"


@pytest.mark.asyncio
async def test_max_bad_records_over_threshold_fails(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "ok"}\n{"name": "bad1"}\n{"name": "bad2"}\n{"name": "bad3"}\n'
    cfg = _ndjson_config("t_over") | {"maxBadRecords": 2}
    rec = await runner.run_load(project="p", job_id="j4", load_config=cfg, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "got 3" in rec.error_result["message"]


# ---------- ignoreUnknownValues -------------------------------------------


@pytest.mark.asyncio
async def test_ignore_unknown_values_strips_extra_ndjson_keys(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "alice", "extra": "drop_me", "nested": {"k": 1}}\n'
    cfg = _ndjson_config("t_iuv_json") | {"ignoreUnknownValues": True}
    rec = await runner.run_load(project="p", job_id="j5", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 1
    assert rec.load_stats["badRecords"] == "0"
    rows = await runner._conn.execute('SELECT id, name FROM "p:d"."t_iuv_json"')
    assert rows == [(1, "alice")]


@pytest.mark.asyncio
async def test_unknown_values_without_flag_count_as_bad(runner: LoadRunner) -> None:
    body = b'{"id": 1, "name": "alice", "extra": "x"}\n'
    cfg = _ndjson_config("t_no_iuv")  # default ignoreUnknownValues=False, maxBadRecords=0
    rec = await runner.run_load(project="p", job_id="j6", load_config=cfg, data=body)
    assert rec.error_result is not None
    assert "unknown field" in rec.error_result["message"]


@pytest.mark.asyncio
async def test_ignore_unknown_values_drops_extra_csv_columns(runner: LoadRunner) -> None:
    """Wide CSV rows are accepted (extras dropped) under ignoreUnknownValues."""
    body = b"id,name\n1,alice,extra1,extra2\n2,bob,extra3,extra4\n"
    cfg = _csv_config("t_iuv_csv") | {"ignoreUnknownValues": True}
    rec = await runner.run_load(project="p", job_id="j7", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2
    assert rec.load_stats["badRecords"] == "0"


# ---------- CSV column-count mismatch counts as bad-record ----------------


@pytest.mark.asyncio
async def test_csv_short_row_counts_as_bad_record_under_threshold(
    runner: LoadRunner,
) -> None:
    """A row with too few columns is now a bad-record (was fatal previously)."""
    body = b"id,name\n1,alice\n2\n3,carol\n"  # row 2 is missing the name column
    cfg = _csv_config("t_csv_short") | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j8", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2
    assert rec.load_stats["badRecords"] == "1"


@pytest.mark.asyncio
async def test_csv_too_many_columns_without_flag_counts_as_bad_record(
    runner: LoadRunner,
) -> None:
    """Without ignoreUnknownValues, wide rows are bad records, not silent drops."""
    body = b"id,name\n1,alice,extra\n"
    cfg = _csv_config("t_csv_wide")  # no ignoreUnknownValues, no maxBadRecords
    rec = await runner.run_load(project="p", job_id="j9", load_config=cfg, data=body)
    assert rec.error_result is not None
    assert "Too many errors" in rec.error_result["message"]


@pytest.mark.asyncio
async def test_csv_combined_parse_and_validation_errors_share_budget(
    runner: LoadRunner,
) -> None:
    """parse errors + validation errors should both count toward maxBadRecords."""
    body = (
        b"id,name\n"
        b"1,alice\n"
        b"2\n"  # parse error: too few columns
        b",bob\n"  # validation: REQUIRED id missing (empty cell coerces to None)
        b"3,carol\n"
    )
    cfg = _csv_config("t_csv_mix") | {"maxBadRecords": 2}
    rec = await runner.run_load(project="p", job_id="j10", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2
    assert rec.load_stats["badRecords"] == "2"


# ---------- write_truncate behavior with bad rows -------------------------


@pytest.mark.asyncio
async def test_write_truncate_with_too_many_bad_rolls_back(runner: LoadRunner) -> None:
    """Pre-existing rows survive a TRUNCATE-load that fails on bad-records."""
    # Pre-populate via an initial successful load.
    initial = b'{"id": 99, "name": "keeper"}\n'
    await runner.run_load(
        project="p", job_id="j11a", load_config=_ndjson_config("t_trunc"), data=initial
    )
    # Now attempt a truncate-load that has too many bad rows.
    body = b'{"name": "bad1"}\n{"name": "bad2"}\n'
    cfg = _ndjson_config("t_trunc") | {"writeDisposition": "WRITE_TRUNCATE"}
    rec = await runner.run_load(project="p", job_id="j11b", load_config=cfg, data=body)
    assert rec.error_result is not None
    rows = await runner._conn.execute('SELECT id, name FROM "p:d"."t_trunc"')
    assert rows == [(99, "keeper")]
