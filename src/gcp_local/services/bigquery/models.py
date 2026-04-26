"""Domain records for BigQuery resources."""

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from typing import Any, Literal, cast

FieldMode = Literal["NULLABLE", "REQUIRED", "REPEATED"]


@dataclass(frozen=True)
class FieldSchema:
    name: str
    type: str
    mode: FieldMode
    fields: list["FieldSchema"] | None


@dataclass
class DatasetRecord:
    project: str
    dataset_id: str
    create_time: str
    last_modified_time: str
    description: str | None
    labels: dict[str, str]
    location: str
    default_table_expiration_ms: int | None


@dataclass
class TableRecord:
    project: str
    dataset_id: str
    table_id: str
    schema: list[FieldSchema]
    create_time: str
    last_modified_time: str
    description: str | None
    labels: dict[str, str]
    time_partitioning: dict[str, Any] | None
    range_partitioning: dict[str, Any] | None
    clustering: dict[str, Any] | None


@dataclass
class JobRecord:
    project: str
    job_id: str
    job_type: str  # "QUERY" | "DML" | "LOAD"
    state: str  # always "DONE" in v1
    create_time: str
    start_time: str
    end_time: str
    user_email: str
    statement_type: str
    sql: str
    destination_table: tuple[str, str, str] | None
    total_rows: int
    total_bytes_processed: int
    error_result: dict[str, Any] | None
    errors: list[dict[str, Any]] = dc_field(default_factory=list)
    load_config: dict[str, Any] | None = None
    load_stats: dict[str, Any] | None = None


def _field_to_dict(f: FieldSchema) -> dict[str, Any]:
    out: dict[str, Any] = {"name": f.name, "type": f.type, "mode": f.mode}
    if f.fields is not None:
        out["fields"] = [_field_to_dict(s) for s in f.fields]
    return out


def _field_from_dict(raw: dict[str, Any]) -> FieldSchema:
    nested = [_field_from_dict(s) for s in raw["fields"]] if raw.get("fields") is not None else None
    return FieldSchema(
        name=raw["name"],
        type=raw["type"],
        mode=cast(FieldMode, raw["mode"]),
        fields=nested,
    )


def dataset_to_dict(rec: DatasetRecord) -> dict[str, Any]:
    return asdict(rec)


def dataset_from_dict(raw: dict[str, Any]) -> DatasetRecord:
    return DatasetRecord(
        project=raw["project"],
        dataset_id=raw["dataset_id"],
        create_time=raw["create_time"],
        last_modified_time=raw["last_modified_time"],
        description=raw["description"],
        labels=dict(raw.get("labels") or {}),
        location=raw["location"],
        default_table_expiration_ms=raw.get("default_table_expiration_ms"),
    )


def table_to_dict(rec: TableRecord) -> dict[str, Any]:
    return {
        "project": rec.project,
        "dataset_id": rec.dataset_id,
        "table_id": rec.table_id,
        "schema": [_field_to_dict(f) for f in rec.schema],
        "create_time": rec.create_time,
        "last_modified_time": rec.last_modified_time,
        "description": rec.description,
        "labels": dict(rec.labels),
        "time_partitioning": rec.time_partitioning,
        "range_partitioning": rec.range_partitioning,
        "clustering": rec.clustering,
    }


def table_from_dict(raw: dict[str, Any]) -> TableRecord:
    return TableRecord(
        project=raw["project"],
        dataset_id=raw["dataset_id"],
        table_id=raw["table_id"],
        schema=[_field_from_dict(s) for s in raw["schema"]],
        create_time=raw["create_time"],
        last_modified_time=raw["last_modified_time"],
        description=raw.get("description"),
        labels=dict(raw.get("labels") or {}),
        time_partitioning=raw.get("time_partitioning"),
        range_partitioning=raw.get("range_partitioning"),
        clustering=raw.get("clustering"),
    )


def job_to_dict(rec: JobRecord) -> dict[str, Any]:
    payload = asdict(rec)
    if rec.destination_table is not None:
        payload["destination_table"] = list(rec.destination_table)
    return payload


def job_from_dict(raw: dict[str, Any]) -> JobRecord:
    dest = raw.get("destination_table")
    if dest is not None:
        dest = (dest[0], dest[1], dest[2])
    return JobRecord(
        project=raw["project"],
        job_id=raw["job_id"],
        job_type=raw["job_type"],
        state=raw["state"],
        create_time=raw["create_time"],
        start_time=raw["start_time"],
        end_time=raw["end_time"],
        user_email=raw["user_email"],
        statement_type=raw["statement_type"],
        sql=raw["sql"],
        destination_table=dest,
        total_rows=raw["total_rows"],
        total_bytes_processed=raw["total_bytes_processed"],
        error_result=raw.get("error_result"),
        errors=list(raw.get("errors") or []),
        load_config=raw.get("load_config"),
        load_stats=raw.get("load_stats"),
    )
