import pytest

from gcp_local.services.bigquery.engine.info_schema import (
    UnsupportedInfoSchemaView,
    rewrite_info_schema_reference,
)


def test_tables_view_rewrites_to_catalog_select() -> None:
    out = rewrite_info_schema_reference("p", "d", "TABLES")
    assert "_gcp_local_meta.tables" in out
    assert "project = 'p'" in out
    assert "dataset_id = 'd'" in out


def test_columns_view_unnests_schema_json() -> None:
    out = rewrite_info_schema_reference("p", "d", "COLUMNS")
    assert "_gcp_local_meta.tables" in out
    assert "ordinal_position" in out


def test_schemata_view() -> None:
    out = rewrite_info_schema_reference("p", "d", "SCHEMATA")
    assert "_gcp_local_meta.datasets" in out


def test_unsupported_view_raises() -> None:
    with pytest.raises(UnsupportedInfoSchemaView):
        rewrite_info_schema_reference("p", "d", "JOBS_BY_USER")
