"""DuckDB connection lifecycle + catalog bootstrap (spec §5)."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb

_CATALOG_DDL = [
    "CREATE SCHEMA IF NOT EXISTS _gcp_local_meta",
    "CREATE SCHEMA IF NOT EXISTS _gcp_local_jobs",
    """
    CREATE TABLE IF NOT EXISTS _gcp_local_meta.datasets (
        project    VARCHAR NOT NULL,
        dataset_id VARCHAR NOT NULL,
        record     JSON    NOT NULL,
        PRIMARY KEY (project, dataset_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _gcp_local_meta.tables (
        project    VARCHAR NOT NULL,
        dataset_id VARCHAR NOT NULL,
        table_id   VARCHAR NOT NULL,
        record     JSON    NOT NULL,
        PRIMARY KEY (project, dataset_id, table_id)
    )
    """,
]

_SYSTEM_SCHEMAS = {
    "main",
    "information_schema",
    "pg_catalog",
    "_gcp_local_meta",
    "_gcp_local_jobs",
}


class BigQueryConnection:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bq-duckdb")
        self._conn: duckdb.DuckDBPyConnection | None = None

    @classmethod
    def in_memory(cls) -> "BigQueryConnection":
        return cls(":memory:")

    @classmethod
    def on_disk(cls, path: Path) -> "BigQueryConnection":
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(str(path))

    async def startup(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            self._conn = await loop.run_in_executor(self._executor, duckdb.connect, self._db_path)
            for ddl in _CATALOG_DDL:
                await self.execute(ddl)
        except Exception:
            self._executor.shutdown(wait=False)
            raise

    async def shutdown(self) -> None:
        if self._conn is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._conn.close)
            self._conn = None
        self._executor.shutdown(wait=True)

    async def execute(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        assert self._conn is not None, "startup() not called"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._sync_execute, sql, params or [])

    def _sync_execute(self, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
        assert self._conn is not None
        return self._conn.execute(sql, params).fetchall()

    async def reset(self) -> None:
        rows = await self.execute("SELECT schema_name FROM information_schema.schemata")
        for (schema,) in rows:
            if schema in _SYSTEM_SCHEMAS:
                continue
            await self.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        # Drop and recreate the transient jobs schema, plus clear catalog rows.
        await self.execute("DROP SCHEMA IF EXISTS _gcp_local_jobs CASCADE")
        await self.execute("CREATE SCHEMA IF NOT EXISTS _gcp_local_jobs")
        await self.execute("DELETE FROM _gcp_local_meta.tables")
        await self.execute("DELETE FROM _gcp_local_meta.datasets")
