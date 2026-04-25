"""Tests for BigQuery scalar UDF shims registered on the DuckDB connection.

Note: ``register_shims`` is called automatically by ``BigQueryConnection.startup()``.
Tests do NOT call it explicitly — doing so would trigger a DuckDB duplicate-function
error because ``create_function`` does not support overwriting existing UDFs.
"""

import re

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection


@pytest.mark.asyncio
async def test_generate_uuid_returns_uuid_string() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute("SELECT generate_uuid()")
    assert re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        rows[0][0],
    )


@pytest.mark.asyncio
async def test_format_date_basic_token() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute("SELECT bq_format_date('%Y-%m-%d', DATE '2026-04-25')")
    assert rows[0][0] == "2026-04-25"


@pytest.mark.asyncio
async def test_parse_date_basic_token() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute("SELECT bq_parse_date('%Y-%m-%d', '2026-04-25')")
    assert str(rows[0][0]) == "2026-04-25"


@pytest.mark.asyncio
async def test_format_timestamp_with_zone() -> None:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    rows = await conn.execute(
        "SELECT bq_format_timestamp('%Y-%m-%d %H:%M:%S', TIMESTAMP '2026-04-25 12:00:00+00')"
    )
    assert rows[0][0] == "2026-04-25 12:00:00"
