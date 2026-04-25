"""Resource-name parsing and DuckDB identifier construction for BigQuery.

Spec §4.1 (resource names) and §5.1 (logical → DuckDB schema mapping).
"""

import re
from dataclasses import dataclass

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$|^[a-z]$")
_DATASET_RE = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
_TABLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")
_JOB_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")


class InvalidName(ValueError):
    """Raised when a project/dataset/table/job ID or path is malformed."""


@dataclass(frozen=True)
class DatasetRef:
    project: str
    dataset_id: str


@dataclass(frozen=True)
class TableRef:
    project: str
    dataset_id: str
    table_id: str


@dataclass(frozen=True)
class JobRef:
    project: str
    job_id: str


def validate_project_id(s: str) -> None:
    if not _PROJECT_RE.match(s):
        raise InvalidName(f"invalid project id: {s!r}")


def validate_dataset_id(s: str) -> None:
    if not _DATASET_RE.match(s):
        raise InvalidName(f"invalid dataset id: {s!r}")


def validate_table_id(s: str) -> None:
    if not _TABLE_RE.match(s):
        raise InvalidName(f"invalid table id: {s!r}")


def validate_job_id(s: str) -> None:
    if not _JOB_RE.match(s):
        raise InvalidName(f"invalid job id: {s!r}")


def parse_dataset_path(path: str) -> DatasetRef:
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "projects" or parts[2] != "datasets":
        raise InvalidName(f"not a dataset path: {path!r}")
    validate_project_id(parts[1])
    validate_dataset_id(parts[3])
    return DatasetRef(project=parts[1], dataset_id=parts[3])


def parse_table_path(path: str) -> TableRef:
    parts = path.split("/")
    if len(parts) != 6 or parts[0] != "projects" or parts[2] != "datasets" or parts[4] != "tables":
        raise InvalidName(f"not a table path: {path!r}")
    validate_project_id(parts[1])
    validate_dataset_id(parts[3])
    validate_table_id(parts[5])
    return TableRef(project=parts[1], dataset_id=parts[3], table_id=parts[5])


def parse_job_path(path: str) -> JobRef:
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "projects" or parts[2] != "jobs":
        raise InvalidName(f"not a job path: {path!r}")
    validate_project_id(parts[1])
    validate_job_id(parts[3])
    return JobRef(project=parts[1], job_id=parts[3])


def parse_three_part(s: str) -> TableRef:
    """Parse `project.dataset.table` or `project:dataset.table` (with optional surrounding backticks)."""
    s = s.strip().strip("`")
    if ":" in s:
        head, _, tail = s.partition(":")
        if "." not in tail:
            raise InvalidName(f"not a three-part name: {s!r}")
        ds, _, tbl = tail.partition(".")
        project, dataset_id, table_id = head, ds, tbl
    else:
        parts = s.split(".")
        if len(parts) != 3:
            raise InvalidName(f"not a three-part name: {s!r}")
        project, dataset_id, table_id = parts
    validate_project_id(project)
    validate_dataset_id(dataset_id)
    validate_table_id(table_id)
    return TableRef(project=project, dataset_id=dataset_id, table_id=table_id)


def duckdb_schema_name(project: str, dataset_id: str) -> str:
    """The unquoted DuckDB schema name backing a (project, dataset) pair."""
    validate_project_id(project)
    validate_dataset_id(dataset_id)
    return f"{project}:{dataset_id}"


def duckdb_table_qualname(project: str, dataset_id: str, table_id: str) -> str:
    """A fully-quoted `"<schema>"."<table>"` reference safe for DuckDB SQL."""
    validate_table_id(table_id)
    schema = duckdb_schema_name(project, dataset_id)
    return f'"{schema}"."{table_id}"'
