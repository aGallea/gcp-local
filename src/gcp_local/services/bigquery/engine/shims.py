"""BigQuery scalar UDFs registered on the DuckDB connection (spec §9.2).

We name the functions with a ``bq_`` prefix and expose them as Python UDFs.
The translate() layer rewrites ``FORMAT_DATE(...)`` / ``PARSE_DATE(...)`` /
``FORMAT_TIMESTAMP(...)`` / ``PARSE_TIMESTAMP(...)`` calls to ``bq_<name>(...)``.
GENERATE_UUID() is rewritten to generate_uuid(); we register that name too.
"""

import datetime as dt
import uuid

from gcp_local.services.bigquery.engine.connection import BigQueryConnection

_BQ_TO_STRFTIME = {
    "%Y": "%Y",
    "%y": "%y",
    "%m": "%m",
    "%d": "%d",
    "%H": "%H",
    "%M": "%M",
    "%S": "%S",
    "%j": "%j",
    "%a": "%a",
    "%A": "%A",
    "%b": "%b",
    "%B": "%B",
    "%p": "%p",
    "%z": "%z",
    "%F": "%Y-%m-%d",
    "%T": "%H:%M:%S",
    "%f": "%f",
}


def _translate_format(fmt: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(fmt):
        if fmt[i] == "%" and i + 1 < len(fmt):
            token = fmt[i : i + 2]
            if token not in _BQ_TO_STRFTIME:
                raise ValueError(f"unsupported BQ format token: {token}")
            out.append(_BQ_TO_STRFTIME[token])
            i += 2
        else:
            out.append(fmt[i])
            i += 1
    return "".join(out)


def _generate_uuid() -> str:
    return str(uuid.uuid4())


def _bq_format_date(fmt: str, value: dt.date) -> str:
    return value.strftime(_translate_format(fmt))


def _bq_parse_date(fmt: str, value: str) -> dt.date:
    return dt.datetime.strptime(value, _translate_format(fmt)).date()


def _bq_format_timestamp(fmt: str, value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.strftime(_translate_format(fmt))


def _bq_parse_timestamp(fmt: str, value: str) -> dt.datetime:
    parsed = dt.datetime.strptime(value, _translate_format(fmt))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def register_shims(conn: BigQueryConnection) -> None:
    """Register BQ-compatible scalar UDFs on the underlying DuckDB connection.

    Uses ``conn._conn`` directly (a controlled extension point) to access the
    raw DuckDB connection object required by ``create_function``.
    """
    raw = conn._conn
    assert raw is not None, "register_shims called before startup()"
    raw.create_function("generate_uuid", _generate_uuid, [], "VARCHAR")
    raw.create_function("bq_format_date", _bq_format_date, ["VARCHAR", "DATE"], "VARCHAR")
    raw.create_function("bq_parse_date", _bq_parse_date, ["VARCHAR", "VARCHAR"], "DATE")
    raw.create_function(
        "bq_format_timestamp",
        _bq_format_timestamp,
        ["VARCHAR", "TIMESTAMP WITH TIME ZONE"],
        "VARCHAR",
    )
    raw.create_function(
        "bq_parse_timestamp",
        _bq_parse_timestamp,
        ["VARCHAR", "VARCHAR"],
        "TIMESTAMP WITH TIME ZONE",
    )
