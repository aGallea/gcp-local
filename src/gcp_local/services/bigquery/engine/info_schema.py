"""Rewrite BQ INFORMATION_SCHEMA references to selects over our catalog."""

_SUPPORTED = {"TABLES", "COLUMNS", "SCHEMATA"}


class UnsupportedInfoSchemaView(ValueError):
    """Raised for INFORMATION_SCHEMA views we don't expose in v1."""


_TABLES_SQL = (
    "SELECT "
    "  json_extract_string(record, '$.project') AS table_catalog, "
    "  json_extract_string(record, '$.dataset_id') AS table_schema, "
    "  json_extract_string(record, '$.table_id') AS table_name, "
    "  'BASE TABLE' AS table_type, "
    "  json_extract_string(record, '$.create_time') AS creation_time "
    "FROM _gcp_local_meta.tables "
    "WHERE project = '{project}' AND dataset_id = '{dataset}'"
)

_COLUMNS_SQL = (
    "WITH t AS ( "
    "  SELECT project, dataset_id, table_id, "
    "         json_extract(record, '$.schema') AS schema_json "
    "  FROM _gcp_local_meta.tables "
    "  WHERE project = '{project}' AND dataset_id = '{dataset}' "
    ") "
    "SELECT t.project AS table_catalog, t.dataset_id AS table_schema, "
    "       t.table_id AS table_name, "
    "       json_extract_string(f.value, '$.name') AS column_name, "
    "       (f.idx + 1) AS ordinal_position, "
    "       CASE WHEN json_extract_string(f.value, '$.mode') = 'REQUIRED' "
    "            THEN 'NO' ELSE 'YES' END AS is_nullable, "
    "       json_extract_string(f.value, '$.type') AS data_type "
    "FROM t, LATERAL UNNEST(json_extract(t.schema_json, '$[*]')) "
    "  WITH ORDINALITY AS f(value, idx)"
)

_SCHEMATA_SQL = (
    "SELECT "
    "  json_extract_string(record, '$.project') AS catalog_name, "
    "  json_extract_string(record, '$.dataset_id') AS schema_name, "
    "  json_extract_string(record, '$.location') AS location, "
    "  json_extract_string(record, '$.create_time') AS creation_time "
    "FROM _gcp_local_meta.datasets "
    "WHERE project = '{project}' AND dataset_id = '{dataset}'"
)


def rewrite_info_schema_reference(project: str, dataset: str, view: str) -> str:
    """Return a DuckDB SELECT that emulates `<dataset>.INFORMATION_SCHEMA.<view>`."""
    view_upper = view.upper()
    if view_upper not in _SUPPORTED:
        raise UnsupportedInfoSchemaView(
            f"INFORMATION_SCHEMA view {view!r} is not supported in gcp-local v1"
        )
    template = {
        "TABLES": _TABLES_SQL,
        "COLUMNS": _COLUMNS_SQL,
        "SCHEMATA": _SCHEMATA_SQL,
    }[view_upper]
    return f"({template.format(project=project, dataset=dataset)})"
