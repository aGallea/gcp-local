"""BigQuery dataset/table storage backed by the DuckDB catalog."""

import json

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    TableRecord,
    dataset_from_dict,
    dataset_to_dict,
    table_from_dict,
    table_to_dict,
)
from gcp_local.services.bigquery.names import (
    duckdb_schema_name,
    duckdb_table_qualname,
)
from gcp_local.services.bigquery.types import schema_to_duckdb_columns


class DatasetNotFound(KeyError):
    pass


class DatasetAlreadyExists(KeyError):
    pass


class TableNotFound(KeyError):
    pass


class TableAlreadyExists(KeyError):
    pass


class BigQueryStorage:
    def __init__(self, connection: BigQueryConnection) -> None:
        self._conn = connection

    @property
    def connection(self) -> BigQueryConnection:
        return self._conn

    # --- datasets -----------------------------------------------------

    async def create_dataset(self, rec: DatasetRecord) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [rec.project, rec.dataset_id],
        )
        if rows:
            raise DatasetAlreadyExists(f"{rec.project}:{rec.dataset_id}")
        schema_name = duckdb_schema_name(rec.project, rec.dataset_id)
        await self._conn.execute(f'CREATE SCHEMA "{schema_name}"')
        await self._conn.execute(
            "INSERT INTO _gcp_local_meta.datasets VALUES (?, ?, ?)",
            [rec.project, rec.dataset_id, json.dumps(dataset_to_dict(rec))],
        )

    async def get_dataset(self, project: str, dataset_id: str) -> DatasetRecord:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        if not rows:
            raise DatasetNotFound(f"{project}:{dataset_id}")
        return dataset_from_dict(json.loads(rows[0][0]))

    async def list_datasets(self, project: str) -> list[DatasetRecord]:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.datasets WHERE project=? ORDER BY dataset_id",
            [project],
        )
        return [dataset_from_dict(json.loads(r[0])) for r in rows]

    async def update_dataset(self, rec: DatasetRecord) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [rec.project, rec.dataset_id],
        )
        if not rows:
            raise DatasetNotFound(f"{rec.project}:{rec.dataset_id}")
        await self._conn.execute(
            "UPDATE _gcp_local_meta.datasets SET record=? WHERE project=? AND dataset_id=?",
            [json.dumps(dataset_to_dict(rec)), rec.project, rec.dataset_id],
        )

    async def delete_dataset(self, project: str, dataset_id: str, *, delete_contents: bool) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        if not rows:
            raise DatasetNotFound(f"{project}:{dataset_id}")
        tbls = await self._conn.execute(
            "SELECT count(*) FROM _gcp_local_meta.tables WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        if tbls and tbls[0][0] and not delete_contents:
            raise ValueError(f"dataset {project}:{dataset_id} is not empty")
        schema_name = duckdb_schema_name(project, dataset_id)
        await self._conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await self._conn.execute(
            "DELETE FROM _gcp_local_meta.tables WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )
        await self._conn.execute(
            "DELETE FROM _gcp_local_meta.datasets WHERE project=? AND dataset_id=?",
            [project, dataset_id],
        )

    # --- tables -------------------------------------------------------

    async def create_table(self, rec: TableRecord) -> None:
        rows = await self._conn.execute(
            "SELECT 1 FROM _gcp_local_meta.tables WHERE project=? AND dataset_id=? AND table_id=?",
            [rec.project, rec.dataset_id, rec.table_id],
        )
        if rows:
            raise TableAlreadyExists(f"{rec.project}:{rec.dataset_id}.{rec.table_id}")
        # Make sure the dataset exists.
        await self.get_dataset(rec.project, rec.dataset_id)
        qualname = duckdb_table_qualname(rec.project, rec.dataset_id, rec.table_id)
        cols = schema_to_duckdb_columns(rec.schema)
        await self._conn.execute(f"CREATE TABLE {qualname} ({cols})")
        await self._conn.execute(
            "INSERT INTO _gcp_local_meta.tables VALUES (?, ?, ?, ?)",
            [
                rec.project,
                rec.dataset_id,
                rec.table_id,
                json.dumps(table_to_dict(rec)),
            ],
        )

    async def get_table(self, project: str, dataset_id: str, table_id: str) -> TableRecord:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.tables "
            "WHERE project=? AND dataset_id=? AND table_id=?",
            [project, dataset_id, table_id],
        )
        if not rows:
            raise TableNotFound(f"{project}:{dataset_id}.{table_id}")
        return table_from_dict(json.loads(rows[0][0]))

    async def list_tables(self, project: str, dataset_id: str) -> list[TableRecord]:
        rows = await self._conn.execute(
            "SELECT record FROM _gcp_local_meta.tables "
            "WHERE project=? AND dataset_id=? ORDER BY table_id",
            [project, dataset_id],
        )
        return [table_from_dict(json.loads(r[0])) for r in rows]

    async def update_table(self, rec: TableRecord) -> None:
        await self.get_table(rec.project, rec.dataset_id, rec.table_id)
        await self._conn.execute(
            "UPDATE _gcp_local_meta.tables SET record=? "
            "WHERE project=? AND dataset_id=? AND table_id=?",
            [
                json.dumps(table_to_dict(rec)),
                rec.project,
                rec.dataset_id,
                rec.table_id,
            ],
        )

    async def delete_table(self, project: str, dataset_id: str, table_id: str) -> None:
        await self.get_table(project, dataset_id, table_id)
        qualname = duckdb_table_qualname(project, dataset_id, table_id)
        await self._conn.execute(f"DROP TABLE {qualname}")
        await self._conn.execute(
            "DELETE FROM _gcp_local_meta.tables WHERE project=? AND dataset_id=? AND table_id=?",
            [project, dataset_id, table_id],
        )
