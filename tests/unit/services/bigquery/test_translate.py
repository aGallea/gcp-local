import pytest

from gcp_local.services.bigquery.engine.translate import (
    UnsupportedSql,
    translate,
)


class FakeCatalog:
    def __init__(self, tables: dict[tuple[str, str], list[str]]) -> None:
        self._tables = tables

    def list_table_ids(self, project: str, dataset_id: str) -> list[str]:
        return list(self._tables.get((project, dataset_id), []))


def test_translate_simple_select() -> None:
    sql = translate("SELECT 1", FakeCatalog({}))
    assert sql.strip().lower().startswith("select 1")


def test_translate_three_part_name_to_quoted_schema() -> None:
    sql = translate("SELECT * FROM `my-proj.my_ds.users`", FakeCatalog({}))
    assert '"my-proj:my_ds"."users"' in sql


def test_translate_three_part_dotted_unquoted() -> None:
    sql = translate("SELECT * FROM my-proj.my_ds.users", FakeCatalog({}))
    assert '"my-proj:my_ds"."users"' in sql


def test_translate_safe_prefix_to_try() -> None:
    sql = translate("SELECT SAFE.PARSE_DATE('%F','x')", FakeCatalog({}))
    assert "TRY(" in sql.upper()


def test_translate_wildcard_expands_to_union() -> None:
    catalog = FakeCatalog({("p", "d"): ["events_2024_01", "events_2024_02", "users"]})
    sql = translate("SELECT * FROM `p.d.events_*`", catalog)
    assert "events_2024_01" in sql
    assert "events_2024_02" in sql
    assert "users" not in sql
    assert "UNION ALL" in sql.upper()


def test_translate_rejects_legacy_sql_marker() -> None:
    with pytest.raises(UnsupportedSql):
        translate("#legacySQL\nSELECT 1", FakeCatalog({}))


def test_translate_rejects_ml_function() -> None:
    with pytest.raises(UnsupportedSql, match="ML"):
        translate("SELECT * FROM ML.PREDICT(MODEL `m`, TABLE `t`)", FakeCatalog({}))


def test_translate_rejects_st_function() -> None:
    with pytest.raises(UnsupportedSql, match="ST_"):
        translate("SELECT ST_GEOGFROMTEXT('POINT(1 1)')", FakeCatalog({}))


def test_translate_strips_partitioning_clause_in_create_table() -> None:
    sql = translate(
        "CREATE TABLE `p.d.t` (id INT64) PARTITION BY DATE(ts) OPTIONS()",
        FakeCatalog({}),
    )
    assert "PARTITION BY" not in sql.upper()
