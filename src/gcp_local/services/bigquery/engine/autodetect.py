"""Schema inference for inline-payload load jobs (spec §7.1, §7.2).

Pure functions: take parsed rows in, return a list[FieldSchema] out.
No I/O, no DuckDB. Walked over up to ``_SAMPLE_LIMIT`` rows to keep
inference fast on large payloads (matches real BigQuery's ~100-row cap).
"""

import re
from typing import Any

from gcp_local.services.bigquery.models import FieldSchema

_SAMPLE_LIMIT = 100

_RE_INT = re.compile(r"^-?(?:0|[1-9]\d*)$")
_RE_FLOAT = re.compile(r"^-?\d+\.\d+([eE][+-]?\d+)?$|^-?\d+[eE][+-]?\d+$")
_RE_BOOL = re.compile(r"^(true|false)$", re.IGNORECASE)
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


class AutodetectError(ValueError):
    """Raised when schema cannot be inferred (e.g. empty payload)."""


def autodetect_ndjson(rows: list[dict[str, Any]]) -> list[FieldSchema]:
    """Infer a BQ schema from up to the first 100 NDJSON-parsed objects."""
    if not rows:
        raise AutodetectError("Cannot autodetect schema from empty input")
    sample = rows[:_SAMPLE_LIMIT]
    # Preserve key insertion order: first row's keys first, then any new
    # keys discovered in later rows in the order they appear.
    column_order: list[str] = []
    seen: set[str] = set()
    for row in sample:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                column_order.append(key)
    return [_infer_column(name, [r.get(name) for r in sample]) for name in column_order]


def _infer_column(name: str, values: list[Any]) -> FieldSchema:
    non_null = [v for v in values if v is not None]
    if not non_null:
        # All-null column → default to STRING/NULLABLE (matches BQ behavior
        # of treating undecidable columns as nullable strings).
        return FieldSchema(name=name, type="STRING", mode="NULLABLE", fields=None)

    # REPEATED detection: any list-typed value forces REPEATED inference.
    if all(isinstance(v, list) for v in non_null):
        # Recurse on flattened element values.
        flat = [item for v in non_null for item in v]
        if not flat:
            return FieldSchema(name=name, type="STRING", mode="REPEATED", fields=None)
        elem = _infer_column(name, flat)
        return FieldSchema(name=name, type=elem.type, mode="REPEATED", fields=elem.fields)

    # RECORD detection: all values are dicts.
    if all(isinstance(v, dict) for v in non_null):
        sub_keys: list[str] = []
        sub_seen: set[str] = set()
        for v in non_null:
            for k in v.keys():
                if k not in sub_seen:
                    sub_seen.add(k)
                    sub_keys.append(k)
        sub_fields = [_infer_column(k, [d.get(k) for d in non_null]) for k in sub_keys]
        return FieldSchema(name=name, type="RECORD", mode="NULLABLE", fields=sub_fields)

    types = {type(v) for v in non_null}
    if types == {bool}:
        return FieldSchema(name=name, type="BOOL", mode="NULLABLE", fields=None)
    if types <= {int, bool} and types != {bool}:
        # bool subclasses int in Python; treat any int presence as INT64.
        return FieldSchema(name=name, type="INT64", mode="NULLABLE", fields=None)
    if types <= {int, float, bool} and float in types:
        return FieldSchema(name=name, type="FLOAT64", mode="NULLABLE", fields=None)
    # Anything mixed or string-typed → STRING.
    return FieldSchema(name=name, type="STRING", mode="NULLABLE", fields=None)


def autodetect_csv(rows: list[list[str]], *, has_header: bool) -> list[FieldSchema]:
    """Infer a BQ schema from up to 100 CSV data rows.

    ``rows`` is the full list of parsed rows. ``has_header=True`` treats
    rows[0] as the header (column names); ``has_header=False`` synthesizes
    column names ``string_field_0``, ``string_field_1``, ... and includes
    rows[0] as data.
    """
    if not rows:
        raise AutodetectError("Cannot autodetect schema from empty input")
    if has_header:
        header = rows[0]
        data = rows[1 : 1 + _SAMPLE_LIMIT]
        if not data:
            raise AutodetectError("Cannot autodetect schema from header-only CSV")
    else:
        if not rows[0]:
            raise AutodetectError("Cannot autodetect schema from empty CSV")
        header = [f"string_field_{i}" for i in range(len(rows[0]))]
        data = rows[: _SAMPLE_LIMIT]

    columns: list[FieldSchema] = []
    for col_idx, name in enumerate(header):
        cells = [row[col_idx] for row in data if col_idx < len(row)]
        columns.append(FieldSchema(name=name, type=_infer_csv_cell_type(cells), mode="NULLABLE", fields=None))
    return columns


def _infer_csv_cell_type(cells: list[str]) -> str:
    non_empty = [c for c in cells if c != ""]
    if not non_empty:
        return "STRING"
    if all(_RE_BOOL.match(c) for c in non_empty):
        return "BOOL"
    if all(_RE_INT.match(c) for c in non_empty):
        return "INT64"
    if all(_RE_INT.match(c) or _RE_FLOAT.match(c) for c in non_empty) and any(
        _RE_FLOAT.match(c) for c in non_empty
    ):
        return "FLOAT64"
    if all(_RE_DATE.match(c) for c in non_empty):
        return "DATE"
    if all(_RE_TIMESTAMP.match(c) for c in non_empty):
        return "TIMESTAMP"
    return "STRING"
