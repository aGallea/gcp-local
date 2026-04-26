"""Load-job execution: parse → resolve schema → apply dispositions → INSERT.

Spec sections: §6 (source-format parsing), §7 (schema resolution),
§8 (dispositions), §9 (execution), §10 (job-model integration).
"""

import csv
import io
import json
from typing import Any

from gcp_local.services.bigquery.engine._time import now_epoch_ms_str
from gcp_local.services.bigquery.engine.autodetect import (
    AutodetectError,
    autodetect_csv,
    autodetect_ndjson,
)
from gcp_local.services.bigquery.engine.coerce import row_to_values, validate_row
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.models import (
    FieldSchema,
    JobRecord,
    TableRecord,
)
from gcp_local.services.bigquery.names import duckdb_table_qualname
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    TableNotFound,
)
from gcp_local.services.bigquery.types import (
    UnsupportedType,
    parse_table_schema,
)

_SUPPORTED_SOURCE_FORMATS = {"NEWLINE_DELIMITED_JSON", "CSV"}
_SUPPORTED_CSV_ENCODINGS = {"UTF-8", "UTF8", "ISO-8859-1", "LATIN-1"}


class LoadRunner:
    """Executes load jobs against the shared BigQuery DuckDB connection."""

    def __init__(self, connection: BigQueryConnection, storage: BigQueryStorage) -> None:
        self._conn = connection
        self._storage = storage

    async def run_load(
        self,
        *,
        project: str,
        job_id: str,
        load_config: dict[str, Any],
        data: bytes,
    ) -> JobRecord:
        start = now_epoch_ms_str()
        try:
            dest = _require_destination(load_config)
            source_format = (load_config.get("sourceFormat") or "").upper()
            if source_format not in _SUPPORTED_SOURCE_FORMATS:
                return self._fail(
                    project,
                    job_id,
                    load_config,
                    start,
                    "invalid",
                    f"Unsupported sourceFormat: {source_format!r}",
                )
            if source_format == "NEWLINE_DELIMITED_JSON":
                rows = _parse_ndjson(data)
                schema = await self._resolve_schema_ndjson(load_config, dest, rows)
            else:  # CSV
                csv_rows, has_header = _parse_csv(data, load_config)
                schema = await self._resolve_schema_csv(load_config, dest, csv_rows, has_header)
                rows = _csv_to_dict_rows(csv_rows, has_header, schema)
            await self._ensure_table(dest, schema, load_config)
            disp = (load_config.get("writeDisposition") or "WRITE_APPEND").upper()
            if disp == "WRITE_TRUNCATE":
                await self._conn.execute("BEGIN")
                try:
                    await self._apply_write_disposition(dest, load_config)
                    inserted = await self._insert_rows(dest, schema, rows)
                except Exception:
                    await self._conn.execute("ROLLBACK")
                    raise
                await self._conn.execute("COMMIT")
            else:
                await self._apply_write_disposition(dest, load_config)
                inserted = await self._insert_rows(dest, schema, rows)
            return self._success(
                project=project,
                job_id=job_id,
                load_config=load_config,
                start=start,
                dest=dest,
                input_bytes=len(data),
                output_rows=inserted,
            )
        except _LoadError as e:
            return self._fail(project, job_id, load_config, start, e.reason, str(e))
        except TableNotFound as e:
            return self._fail(project, job_id, load_config, start, "notFound", str(e))
        except (AutodetectError, UnsupportedType, ValueError) as e:
            return self._fail(project, job_id, load_config, start, "invalid", str(e))
        except Exception as e:
            return self._fail(project, job_id, load_config, start, "internalError", str(e))

    # ------------------------------------------------------------------
    # Schema resolution

    async def _resolve_schema_ndjson(
        self,
        load_config: dict[str, Any],
        dest: tuple[str, str, str],
        rows: list[dict[str, Any]],
    ) -> list[FieldSchema]:
        explicit = (load_config.get("schema") or {}).get("fields")
        if explicit:
            return parse_table_schema(explicit)
        if load_config.get("autodetect"):
            return autodetect_ndjson(rows)
        try:
            return (await self._storage.get_table(*dest)).schema
        except TableNotFound:
            raise _LoadError(
                "invalid",
                "Load configuration must specify schema or autodetect",
            ) from None

    async def _resolve_schema_csv(
        self,
        load_config: dict[str, Any],
        dest: tuple[str, str, str],
        csv_rows: list[list[str]],
        has_header: bool,
    ) -> list[FieldSchema]:
        explicit = (load_config.get("schema") or {}).get("fields")
        if explicit:
            return parse_table_schema(explicit)
        if load_config.get("autodetect"):
            return autodetect_csv(csv_rows, has_header=has_header)
        try:
            return (await self._storage.get_table(*dest)).schema
        except TableNotFound:
            raise _LoadError(
                "invalid",
                "Load configuration must specify schema or autodetect",
            ) from None

    # ------------------------------------------------------------------
    # Table existence + create

    async def _ensure_table(
        self,
        dest: tuple[str, str, str],
        schema: list[FieldSchema],
        load_config: dict[str, Any],
    ) -> None:
        create_disp = (load_config.get("createDisposition") or "CREATE_IF_NEEDED").upper()
        try:
            await self._storage.get_table(*dest)
            return
        except TableNotFound:
            pass
        if create_disp == "CREATE_NEVER":
            raise _LoadError(
                "notFound",
                f"Not found: Table {dest[0]}:{dest[1]}.{dest[2]}",
            )
        # CREATE_IF_NEEDED: materialize the table now.
        now = now_epoch_ms_str()
        rec = TableRecord(
            project=dest[0],
            dataset_id=dest[1],
            table_id=dest[2],
            schema=schema,
            create_time=now,
            last_modified_time=now,
            description=None,
            labels={},
            time_partitioning=None,
            range_partitioning=None,
            clustering=None,
        )
        await self._storage.create_table(rec)

    # ------------------------------------------------------------------
    # Write disposition

    async def _apply_write_disposition(
        self,
        dest: tuple[str, str, str],
        load_config: dict[str, Any],
    ) -> None:
        disp = (load_config.get("writeDisposition") or "WRITE_APPEND").upper()
        qualname = duckdb_table_qualname(*dest)
        if disp == "WRITE_APPEND":
            return
        if disp == "WRITE_TRUNCATE":
            await self._conn.execute(f"DELETE FROM {qualname}")
            return
        if disp == "WRITE_EMPTY":
            rows = await self._conn.execute(f"SELECT 1 FROM {qualname} LIMIT 1")
            if rows:
                raise _LoadError(
                    "duplicate",
                    f"Already Exists: Table {dest[0]}:{dest[1]}.{dest[2]} is not empty",
                )
            return
        raise _LoadError("invalid", f"Unknown writeDisposition: {disp!r}")

    # ------------------------------------------------------------------
    # Insert

    async def _insert_rows(
        self,
        dest: tuple[str, str, str],
        schema: list[FieldSchema],
        rows: list[dict[str, Any]],
    ) -> int:
        if not rows:
            return 0
        # Validate every row up front; load jobs are all-or-nothing.
        all_errors: list[str] = []
        for i, row in enumerate(rows):
            errs = validate_row(row, schema)
            for e in errs:
                all_errors.append(f"row {i}: {e}")
        if all_errors:
            head = all_errors[:5]
            raise _LoadError(
                "invalid",
                f"{len(all_errors)} row validation error(s); first: " + "; ".join(head),
            )
        qualname = duckdb_table_qualname(*dest)
        placeholders = ",".join("(" + ",".join(["?"] * len(schema)) + ")" for _ in rows)
        params: list[Any] = [v for row in rows for v in row_to_values(row, schema)]
        await self._conn.execute(f"INSERT INTO {qualname} VALUES {placeholders}", params)
        return len(rows)

    # ------------------------------------------------------------------
    # Job record builders

    def _success(
        self,
        *,
        project: str,
        job_id: str,
        load_config: dict[str, Any],
        start: str,
        dest: tuple[str, str, str],
        input_bytes: int,
        output_rows: int,
    ) -> JobRecord:
        end = now_epoch_ms_str()
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="LOAD",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type="",
            sql="",
            destination_table=dest,
            total_rows=output_rows,
            total_bytes_processed=0,
            error_result=None,
            errors=[],
            load_config=load_config,
            load_stats={
                "inputFiles": "1",
                "inputFileBytes": str(input_bytes),
                "outputRows": str(output_rows),
                "outputBytes": str(input_bytes),
                "badRecords": "0",
            },
        )

    def _fail(
        self,
        project: str,
        job_id: str,
        load_config: dict[str, Any],
        start: str,
        reason: str,
        message: str,
    ) -> JobRecord:
        end = now_epoch_ms_str()
        err = {"reason": reason, "message": message, "domain": "global"}
        return JobRecord(
            project=project,
            job_id=job_id,
            job_type="LOAD",
            state="DONE",
            create_time=start,
            start_time=start,
            end_time=end,
            user_email="local@gcp-local.invalid",
            statement_type="",
            sql="",
            destination_table=None,
            total_rows=0,
            total_bytes_processed=0,
            error_result=err,
            errors=[err],
            load_config=load_config,
            load_stats=None,
        )


# ----------------------------------------------------------------------
# Helpers


class _LoadError(Exception):
    """Raised internally to short-circuit run_load with a failed JobRecord."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _require_destination(load_config: dict[str, Any]) -> tuple[str, str, str]:
    dest = load_config.get("destinationTable") or {}
    project = dest.get("projectId")
    dataset_id = dest.get("datasetId")
    table_id = dest.get("tableId")
    if not (project and dataset_id and table_id):
        raise _LoadError(
            "invalid",
            "Load configuration must include destinationTable.{projectId,datasetId,tableId}",
        )
    return project, dataset_id, table_id


def _parse_ndjson(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8")
    rows: list[dict[str, Any]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise _LoadError("invalid", f"Failed to parse JSON: line {i}: {e}") from e
        if not isinstance(obj, dict):
            raise _LoadError(
                "invalid",
                f"NDJSON line {i} must be a JSON object, got {type(obj).__name__}",
            )
        rows.append(obj)
    return rows


_NULL_SENTINEL = object()


def _parse_csv(
    data: bytes,
    load_config: dict[str, Any],
) -> tuple[list[list[str]], bool]:
    encoding = (load_config.get("encoding") or "UTF-8").upper().replace("_", "-")
    if encoding not in _SUPPORTED_CSV_ENCODINGS:
        raise _LoadError("invalid", f"Unsupported CSV encoding: {encoding!r}")
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as e:
        raise _LoadError("invalid", f"CSV decode failed: {e}") from e
    delimiter = load_config.get("fieldDelimiter") or ","
    quotechar = load_config.get("quote") or '"'
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar=quotechar)
    rows = [r for r in reader if r]
    skip = int(load_config.get("skipLeadingRows") or 0)
    has_header = skip >= 1
    if has_header and skip > 1:
        # BQ semantics: skip N rows total; row 0 is header only when skip==1.
        # When skip>1, drop those rows entirely (they are pre-header garbage)
        # and continue treating row N as header.
        rows = rows[skip - 1 :]
    null_marker = load_config.get("nullMarker") or ""
    if null_marker:
        rows = [
            [_NULL_SENTINEL if c == null_marker else c for c in r]  # type: ignore[misc]
            for r in rows
        ]
    return rows, has_header


def _csv_to_dict_rows(
    csv_rows: list[list[str]],
    has_header: bool,
    schema: list[FieldSchema],
) -> list[dict[str, Any]]:
    if has_header:
        header = csv_rows[0]
        data = csv_rows[1:]
    else:
        header = [f.name for f in schema]
        data = csv_rows

    by_name = {f.name: f for f in schema}
    out: list[dict[str, Any]] = []
    for row_idx, row in enumerate(data):
        if len(row) != len(header):
            raise _LoadError(
                "invalid",
                f"CSV row {row_idx} has {len(row)} columns, expected {len(header)}",
            )
        payload: dict[str, Any] = {}
        for col_idx, cell in enumerate(row):
            name = header[col_idx]
            if cell is _NULL_SENTINEL:
                payload[name] = None
            else:
                payload[name] = _coerce_csv_cell(cell, by_name.get(name))
        out.append(payload)
    return out


def _coerce_csv_cell(cell: str, field: FieldSchema | None) -> Any:
    if field is None:
        return cell
    if cell == "" and field.mode != "REQUIRED":
        return None
    match field.type:
        case "INT64" | "INTEGER":
            return int(cell)
        case "FLOAT64" | "FLOAT" | "NUMERIC" | "BIGNUMERIC":
            return float(cell)
        case "BOOL" | "BOOLEAN":
            return cell.strip().lower() == "true"
        case _:
            return cell
