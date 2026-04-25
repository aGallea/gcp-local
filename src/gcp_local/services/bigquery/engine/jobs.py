"""Synchronous job execution + result paging (spec §6)."""

import base64
import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass

import duckdb
import sqlglot

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.translate import (
    UnsupportedSql,
    translate,
)
from gcp_local.services.bigquery.errors import InvalidQuery, JobNotFound
from gcp_local.services.bigquery.models import FieldSchema, JobRecord
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetNotFound,
    TableNotFound,
)


@dataclass
class JobPage:
    rows: list[tuple]  # type: ignore[type-arg]
    schema: list[FieldSchema]
    next_page_token: str | None


def _now_epoch_ms_str() -> str:
    """Return current time as milliseconds-since-epoch string (BQ REST API format)."""
    return str(int(dt.datetime.now(tz=dt.UTC).timestamp() * 1000))


def _encode_token(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _decode_token(token: str | None) -> int:
    if not token:
        return 0
    try:
        return int(base64.urlsafe_b64decode(token.encode("ascii")))
    except Exception as e:
        raise InvalidQuery(f"invalid pageToken: {token!r}") from e


class JobRunner:
    def __init__(self, connection: BigQueryConnection, storage: BigQueryStorage) -> None:
        self._conn = connection
        self._storage = storage
        self._jobs: dict[tuple[str, str], JobRecord] = {}
        self._job_ended_at: dict[tuple[str, str], float] = {}
        self._job_schemas: dict[str, list[FieldSchema]] = {}
        self._clock: Callable[[], float] = time.monotonic

    def set_clock(self, clock: Callable[[], float]) -> None:
        self._clock = clock

    async def run_query(self, project: str, job_id: str, sql: str) -> JobRecord:
        start = _now_epoch_ms_str()
        statement_type = _statement_type(sql)
        try:
            translated = await self._translate(project, sql)
            if statement_type == "SELECT":
                rec = await self._materialize_select(project, job_id, sql, translated, start)
            else:
                rec = await self._run_dml(project, job_id, sql, translated, start, statement_type)
        except (UnsupportedSql, sqlglot.errors.ParseError, ValueError, InvalidQuery) as e:
            rec = self._failed_record(
                project, job_id, sql, start, statement_type, "invalidQuery", str(e)
            )
        except (DatasetNotFound, TableNotFound) as e:
            rec = self._failed_record(
                project, job_id, sql, start, statement_type, "notFound", str(e)
            )
        except duckdb.CatalogException as e:
            # Table/schema not found in DuckDB catalog (e.g., unknown table reference).
            rec = self._failed_record(
                project, job_id, sql, start, statement_type, "notFound", str(e)
            )
        except Exception as e:
            rec = self._failed_record(
                project, job_id, sql, start, statement_type, "internalError", str(e)
            )
        self._jobs[(project, job_id)] = rec
        self._job_ended_at[(project, job_id)] = self._clock()
        return rec

    async def _translate(self, project: str, sql: str) -> str:
        ids_by_dataset: dict[str, list[str]] = {}

        class _Cat:
            def list_table_ids(self_inner, p: str, d: str) -> list[str]:
                key = f"{p}/{d}"
                return ids_by_dataset.get(key, [])

        # Pre-fetch wildcard candidates only when wildcard syntax is detected.
        if "*`" in sql or "*'" in sql or "_*" in sql:
            datasets = await self._storage.list_datasets(project)
            for ds in datasets:
                tables = await self._storage.list_tables(project, ds.dataset_id)
                ids_by_dataset[f"{project}/{ds.dataset_id}"] = [t.table_id for t in tables]

        return translate(sql, _Cat())

    async def _materialize_select(
        self,
        project: str,
        job_id: str,
        sql: str,
        translated: str,
        start: str,
    ) -> JobRecord:
        temp_qual = f'"_gcp_local_jobs"."_job_{job_id}"'
        await self._conn.execute(f"CREATE TABLE {temp_qual} AS {translated}")
        count_rows = await self._conn.execute(f"SELECT count(*) FROM {temp_qual}")
        total = int(count_rows[0][0]) if count_rows else 0
        schema = await self._infer_schema(temp_qual)
        self._job_schemas[job_id] = schema
        end = _now_epoch_ms_str()
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="QUERY",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type="SELECT",
            sql=sql,
            destination_table=("_gcp_local", "_gcp_local_jobs", f"_job_{job_id}"),
            total_rows=total,
            total_bytes_processed=0,
            error_result=None,
            errors=[],
        )

    async def _run_dml(
        self,
        project: str,
        job_id: str,
        sql: str,
        translated: str,
        start: str,
        statement_type: str,
    ) -> JobRecord:
        await self._conn.execute(translated)
        end = _now_epoch_ms_str()
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="DML",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type=statement_type,
            sql=sql,
            destination_table=None,
            total_rows=0,
            total_bytes_processed=0,
            error_result=None,
            errors=[],
        )

    def _failed_record(
        self,
        project: str,
        job_id: str,
        sql: str,
        start: str,
        statement_type: str,
        reason: str,
        message: str,
    ) -> JobRecord:
        end = _now_epoch_ms_str()
        err = {"reason": reason, "message": message, "domain": "global"}
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="QUERY" if statement_type == "SELECT" else "DML",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type=statement_type,
            sql=sql,
            destination_table=None,
            total_rows=0,
            total_bytes_processed=0,
            error_result=err,
            errors=[err],
        )

    async def _infer_schema(self, qualname: str) -> list[FieldSchema]:
        rows = await self._conn.execute(f"DESCRIBE {qualname}")
        out: list[FieldSchema] = []
        for col_name, col_type, *_ in rows:
            out.append(
                FieldSchema(
                    name=str(col_name),
                    type=_duckdb_to_bq_type(str(col_type)),
                    mode="NULLABLE",
                    fields=None,
                )
            )
        return out

    async def get(self, project: str, job_id: str) -> JobRecord:
        try:
            return self._jobs[(project, job_id)]
        except KeyError:
            raise JobNotFound(f"{project}:{job_id}") from None

    async def list_jobs(self, project: str) -> list[JobRecord]:
        return [r for (p, _j), r in self._jobs.items() if p == project]

    async def cancel(self, project: str, job_id: str) -> JobRecord:
        """No-op success in v1 — queries run synchronously so there's nothing to cancel."""
        return await self.get(project, job_id)

    async def read_page(self, job_id: str, *, page_size: int, page_token: str | None) -> JobPage:
        offset = _decode_token(page_token)
        schema = self._job_schemas.get(job_id, [])
        rows = await self._conn.execute(
            f'SELECT * FROM "_gcp_local_jobs"."_job_{job_id}" LIMIT ? OFFSET ?',
            [page_size, offset],
        )
        next_off = offset + len(rows)
        total_rows_q = await self._conn.execute(
            f'SELECT count(*) FROM "_gcp_local_jobs"."_job_{job_id}"'
        )
        total = int(total_rows_q[0][0]) if total_rows_q else 0
        return JobPage(
            rows=list(rows),
            schema=schema,
            next_page_token=_encode_token(next_off) if next_off < total else None,
        )

    async def sweep_expired(self, ttl_seconds: float) -> None:
        now = self._clock()
        expired = [
            key
            for key, ended in self._job_ended_at.items()
            # Evict if TTL exceeded OR if ended_at is in the future relative to
            # the current clock (handles backward clock jumps in tests where the
            # clock is set after some jobs were recorded with wall time).
            if (now - ended) > ttl_seconds or ended > now
        ]
        for key in expired:
            _project, job_id = key
            await self._conn.execute(f'DROP TABLE IF EXISTS "_gcp_local_jobs"."_job_{job_id}"')
            self._jobs.pop(key, None)
            self._job_ended_at.pop(key, None)
            self._job_schemas.pop(job_id, None)


def _statement_type(sql: str) -> str:
    head = sql.lstrip().split(None, 1)[0].upper()
    if head in {"INSERT", "UPDATE", "DELETE", "MERGE"}:
        return head
    return "SELECT"


_DUCKDB_TO_BQ: dict[str, str] = {
    "VARCHAR": "STRING",
    "BLOB": "BYTES",
    "BIGINT": "INT64",
    "INTEGER": "INT64",
    "DOUBLE": "FLOAT64",
    "BOOLEAN": "BOOL",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP WITH TIME ZONE": "TIMESTAMP",
    "TIMESTAMP": "DATETIME",
    "JSON": "JSON",
}


def _duckdb_to_bq_type(duckdb_type: str) -> str:
    base = duckdb_type.upper().split("(", 1)[0].strip()
    return _DUCKDB_TO_BQ.get(base, "STRING")
