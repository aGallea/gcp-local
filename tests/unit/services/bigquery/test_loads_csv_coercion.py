"""CSV cell coercion for DATE / TIME / DATETIME / TIMESTAMP / JSON columns."""

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
        "sourceFormat": "CSV",
        "skipLeadingRows": 1,
        "schema": {"fields": fields},
    }


# ---------- DATE -----------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_date_happy_path(runner: LoadRunner) -> None:
    body = b"id,d\n1,2024-01-15\n2,2025-12-31\n"
    cfg = _config("t_date", [{"name": "id", "type": "INT64"}, {"name": "d", "type": "DATE"}])
    rec = await runner.run_load(project="p", job_id="j_date", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT d FROM "p:d"."t_date" ORDER BY id')
    assert [r[0] for r in rows] == [dt.date(2024, 1, 15), dt.date(2025, 12, 31)]


@pytest.mark.asyncio
async def test_csv_date_malformed_buckets_under_max_bad_records(
    runner: LoadRunner,
) -> None:
    body = b"id,d\n1,2024-01-15\n2,not-a-date\n3,2026-04-29\n"
    cfg = _config(
        "t_date_bad", [{"name": "id", "type": "INT64"}, {"name": "d", "type": "DATE"}]
    ) | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j_date_bad", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.total_rows == 2
    assert rec.load_stats["badRecords"] == "1"


# ---------- TIMESTAMP ------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_timestamp_accepts_z_suffix_and_utc(runner: LoadRunner) -> None:
    body = (
        b"id,ts\n"
        b"1,2024-01-15T12:34:56Z\n"
        b"2,2024-01-15 12:34:56 UTC\n"
        b"3,2024-01-15 12:34:56.789+02:00\n"
        b"4,2024-01-15 12:34:56\n"  # no tz → assume UTC
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
    # +02:00 normalizes to 10:34 UTC.
    assert rows[2][1] == dt.datetime(2024, 1, 15, 10, 34, 56, 789000, tzinfo=dt.UTC)
    assert rows[3][1] == dt.datetime(2024, 1, 15, 12, 34, 56, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_csv_timestamp_malformed_is_bad_record(runner: LoadRunner) -> None:
    body = b"id,ts\n1,2024-01-15T12:34:56Z\n2,not-a-time\n"
    cfg = _config(
        "t_ts_bad",
        [{"name": "id", "type": "INT64"}, {"name": "ts", "type": "TIMESTAMP"}],
    ) | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j_ts_bad", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.load_stats["badRecords"] == "1"


# ---------- DATETIME -------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_datetime_naive(runner: LoadRunner) -> None:
    body = b"id,dt\n1,2024-01-15T12:34:56\n2,2024-01-15 06:00:00\n"
    cfg = _config("t_dt", [{"name": "id", "type": "INT64"}, {"name": "dt", "type": "DATETIME"}])
    rec = await runner.run_load(project="p", job_id="j_dt", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT dt FROM "p:d"."t_dt" ORDER BY id')
    assert rows[0][0] == dt.datetime(2024, 1, 15, 12, 34, 56)
    assert rows[1][0] == dt.datetime(2024, 1, 15, 6, 0, 0)


@pytest.mark.asyncio
async def test_csv_datetime_with_tz_is_rejected(runner: LoadRunner) -> None:
    """DATETIME has no timezone; an offset should be rejected as bad-record."""
    body = b"id,dt\n1,2024-01-15T12:34:56+00:00\n"
    cfg = _config("t_dt_tz", [{"name": "id", "type": "INT64"}, {"name": "dt", "type": "DATETIME"}])
    rec = await runner.run_load(project="p", job_id="j_dt_tz", load_config=cfg, data=body)
    # maxBadRecords default 0 → fails
    assert rec.error_result is not None
    assert "DATETIME" in rec.error_result["message"]


# ---------- TIME -----------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_time(runner: LoadRunner) -> None:
    body = b"id,t\n1,12:34:56\n2,06:00:00.123\n"
    cfg = _config("t_time", [{"name": "id", "type": "INT64"}, {"name": "t", "type": "TIME"}])
    rec = await runner.run_load(project="p", job_id="j_time", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT t FROM "p:d"."t_time" ORDER BY id')
    assert rows[0][0] == dt.time(12, 34, 56)
    assert rows[1][0] == dt.time(6, 0, 0, 123000)


# ---------- JSON -----------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_json_happy_path(runner: LoadRunner) -> None:
    # CSV value is a JSON object, quoted because it contains commas.
    body = b'id,payload\n1,"{""k"": 1, ""arr"": [1, 2, 3]}"\n'
    cfg = _config("t_json", [{"name": "id", "type": "INT64"}, {"name": "payload", "type": "JSON"}])
    rec = await runner.run_load(project="p", job_id="j_json", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT payload FROM "p:d"."t_json"')
    # DuckDB returns the JSON column as the canonical string. Parse to verify.
    import json as _json

    parsed = _json.loads(rows[0][0])
    assert parsed == {"k": 1, "arr": [1, 2, 3]}


@pytest.mark.asyncio
async def test_csv_json_malformed_is_bad_record(runner: LoadRunner) -> None:
    body = b'id,payload\n1,"{""ok"":1}"\n2,"{not json}"\n'
    cfg = _config(
        "t_json_bad",
        [{"name": "id", "type": "INT64"}, {"name": "payload", "type": "JSON"}],
    ) | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j_json_bad", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.load_stats["badRecords"] == "1"


# ---------- Boolean (broadened acceptance) ---------------------------------


@pytest.mark.asyncio
async def test_csv_bool_accepts_alternative_truthy_values(runner: LoadRunner) -> None:
    """Real BigQuery accepts t/true/1/yes/y (case-insensitive); same for falsey."""
    body = b"id,b\n1,true\n2,T\n3,1\n4,FALSE\n5,0\n6,no\n"
    cfg = _config("t_bool", [{"name": "id", "type": "INT64"}, {"name": "b", "type": "BOOL"}])
    rec = await runner.run_load(project="p", job_id="j_bool", load_config=cfg, data=body)
    assert rec.error_result is None
    rows = await runner._conn.execute('SELECT id, b FROM "p:d"."t_bool" ORDER BY id')
    assert [r[1] for r in rows] == [True, True, True, False, False, False]


@pytest.mark.asyncio
async def test_csv_bool_invalid_is_bad_record(runner: LoadRunner) -> None:
    body = b"id,b\n1,true\n2,maybe\n"
    cfg = _config(
        "t_bool_bad", [{"name": "id", "type": "INT64"}, {"name": "b", "type": "BOOL"}]
    ) | {"maxBadRecords": 1}
    rec = await runner.run_load(project="p", job_id="j_bool_bad", load_config=cfg, data=body)
    assert rec.error_result is None
    assert rec.load_stats["badRecords"] == "1"
