"""NDJSON cell coercion for DATE / TIME / DATETIME / TIMESTAMP columns."""

import datetime as dt
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


def _config(table: str, fields: list[dict]) -> dict:
    return {
        "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": table},
        "sourceFormat": "NEWLINE_DELIMITED_JSON",
        "schema": {"fields": fields},
    }


# ---------- DATE -----------------------------------------------------------


@pytest.mark.asyncio
async def test_ndjson_date_happy_path(runner: LoadRunner) -> None:
    body = b'{"id": 1, "d": "2024-01-15"}\n{"id": 2, "d": "2025-12-31"}\n'
    cfg = _config("t_date", [{"name": "id", "type": "INT64"}, {"name": "d", "type": "DATE"}])
    rec = await runner.run_load(project="p", job_id="j_date", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT d FROM "p:d"."t_date" ORDER BY id')
    assert [r[0] for r in rows] == [dt.date(2024, 1, 15), dt.date(2025, 12, 31)]


@pytest.mark.asyncio
async def test_ndjson_date_malformed_buckets_under_max_bad_records(
    runner: LoadRunner,
) -> None:
    body = (
        b'{"id": 1, "d": "2024-01-15"}\n'
        b'{"id": 2, "d": "not-a-date"}\n'
        b'{"id": 3, "d": "2026-04-29"}\n'
    )
    cfg = _config(
        "t_date_bad", [{"name": "id", "type": "INT64"}, {"name": "d", "type": "DATE"}]
    ) | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j_date_bad", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2
    assert rec.load_stats["badRecords"] == "1"


@pytest.mark.asyncio
async def test_ndjson_date_malformed_aborts_when_over_limit(
    runner: LoadRunner,
) -> None:
    """Malformed temporal values now bucket under maxBadRecords (default 0)."""
    body = b'{"id": 1, "d": "2024-01-15"}\n{"id": 2, "d": "garbage"}\n'
    cfg = _config(
        "t_date_abort",
        [{"name": "id", "type": "INT64"}, {"name": "d", "type": "DATE"}],
    )
    rec = await runner.run_load(project="p", job_id="j_date_abort", load_config=cfg, data=body)
    assert rec.error_result is not None
    assert rec.error_result["reason"] == "invalid"
    assert "DATE" in rec.error_result["message"]


# ---------- TIMESTAMP ------------------------------------------------------


@pytest.mark.asyncio
async def test_ndjson_timestamp_accepts_z_suffix_and_utc(runner: LoadRunner) -> None:
    body = (
        b'{"id": 1, "ts": "2024-01-15T12:34:56Z"}\n'
        b'{"id": 2, "ts": "2024-01-15 12:34:56 UTC"}\n'
        b'{"id": 3, "ts": "2024-01-15 12:34:56.789+02:00"}\n'
        b'{"id": 4, "ts": "2024-01-15 12:34:56"}\n'
    )
    cfg = _config(
        "t_ts",
        [{"name": "id", "type": "INT64"}, {"name": "ts", "type": "TIMESTAMP"}],
    )
    rec = await runner.run_load(project="p", job_id="j_ts", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT id, ts FROM "p:d"."t_ts" ORDER BY id')
    assert rows[0][1] == dt.datetime(2024, 1, 15, 12, 34, 56, tzinfo=dt.UTC)
    assert rows[1][1] == dt.datetime(2024, 1, 15, 12, 34, 56, tzinfo=dt.UTC)
    assert rows[2][1] == dt.datetime(2024, 1, 15, 10, 34, 56, 789000, tzinfo=dt.UTC)
    assert rows[3][1] == dt.datetime(2024, 1, 15, 12, 34, 56, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_ndjson_timestamp_malformed_is_bad_record(runner: LoadRunner) -> None:
    body = b'{"id": 1, "ts": "2024-01-15T12:34:56Z"}\n{"id": 2, "ts": "not-a-time"}\n'
    cfg = _config(
        "t_ts_bad",
        [{"name": "id", "type": "INT64"}, {"name": "ts", "type": "TIMESTAMP"}],
    ) | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j_ts_bad", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.load_stats["badRecords"] == "1"


# ---------- DATETIME -------------------------------------------------------


@pytest.mark.asyncio
async def test_ndjson_datetime_naive(runner: LoadRunner) -> None:
    body = b'{"id": 1, "dt": "2024-01-15T12:34:56"}\n{"id": 2, "dt": "2024-01-15 06:00:00"}\n'
    cfg = _config("t_dt", [{"name": "id", "type": "INT64"}, {"name": "dt", "type": "DATETIME"}])
    rec = await runner.run_load(project="p", job_id="j_dt", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT dt FROM "p:d"."t_dt" ORDER BY id')
    assert rows[0][0] == dt.datetime(2024, 1, 15, 12, 34, 56)
    assert rows[1][0] == dt.datetime(2024, 1, 15, 6, 0, 0)


@pytest.mark.asyncio
async def test_ndjson_datetime_with_tz_is_rejected(runner: LoadRunner) -> None:
    """DATETIME has no timezone; an offset should be rejected as bad-record."""
    body = b'{"id": 1, "dt": "2024-01-15T12:34:56+00:00"}\n'
    cfg = _config("t_dt_tz", [{"name": "id", "type": "INT64"}, {"name": "dt", "type": "DATETIME"}])
    rec = await runner.run_load(project="p", job_id="j_dt_tz", load_config=cfg, data=body)
    assert rec.error_result is not None
    assert "DATETIME" in rec.error_result["message"]


# ---------- TIME -----------------------------------------------------------


@pytest.mark.asyncio
async def test_ndjson_time(runner: LoadRunner) -> None:
    body = b'{"id": 1, "t": "12:34:56"}\n{"id": 2, "t": "06:00:00.123"}\n'
    cfg = _config("t_time", [{"name": "id", "type": "INT64"}, {"name": "t", "type": "TIME"}])
    rec = await runner.run_load(project="p", job_id="j_time", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT t FROM "p:d"."t_time" ORDER BY id')
    assert rows[0][0] == dt.time(12, 34, 56)
    assert rows[1][0] == dt.time(6, 0, 0, 123000)


# ---------- Pass-through cases --------------------------------------------


@pytest.mark.asyncio
async def test_ndjson_non_temporal_types_pass_through(runner: LoadRunner) -> None:
    """INT64 / FLOAT64 / BOOL / STRING already arrive as native JSON types."""
    body = b'{"id": 1, "name": "alice", "score": 9.5, "active": true}\n'
    cfg = _config(
        "t_passthru",
        [
            {"name": "id", "type": "INT64"},
            {"name": "name", "type": "STRING"},
            {"name": "score", "type": "FLOAT64"},
            {"name": "active", "type": "BOOL"},
        ],
    )
    rec = await runner.run_load(project="p", job_id="j_pt", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT id, name, score, active FROM "p:d"."t_passthru"')
    assert rows[0] == (1, "alice", 9.5, True)


@pytest.mark.asyncio
async def test_ndjson_temporal_null_passes_through(runner: LoadRunner) -> None:
    """JSON null on a NULLABLE temporal column maps to SQL NULL."""
    body = b'{"id": 1, "d": null}\n{"id": 2, "d": "2024-01-15"}\n'
    cfg = _config("t_date_null", [{"name": "id", "type": "INT64"}, {"name": "d", "type": "DATE"}])
    rec = await runner.run_load(project="p", job_id="j_dnull", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT d FROM "p:d"."t_date_null" ORDER BY id')
    assert rows[0][0] is None
    assert rows[1][0] == dt.date(2024, 1, 15)


@pytest.mark.asyncio
async def test_ndjson_unknown_field_with_bad_temporal_value(runner: LoadRunner) -> None:
    """Unknown fields skip schema-driven coercion (no field in schema)."""
    body = b'{"id": 1, "extra": "not-a-date"}\n'
    cfg = _config(
        "t_unknown",
        [{"name": "id", "type": "INT64"}],
    ) | {"ignoreUnknownValues": True}
    rec = await runner.run_load(project="p", job_id="j_unk", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 1
