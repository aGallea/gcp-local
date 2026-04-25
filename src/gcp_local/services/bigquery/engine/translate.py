"""sqlglot-driven BigQuery → DuckDB translation pipeline (spec §6.2, §9)."""

import re
from typing import Protocol, cast

import sqlglot
from sqlglot import exp

from gcp_local.services.bigquery.engine.info_schema import (
    UnsupportedInfoSchemaView,
    rewrite_info_schema_reference,
)


class CatalogLookup(Protocol):
    def list_table_ids(self, project: str, dataset_id: str) -> list[str]: ...


class UnsupportedSql(ValueError):
    """Raised for SQL features rejected in v1 (legacy SQL, ML.*, ST_*, scripting)."""


_LEGACY_MARKERS = re.compile(r"^\s*#legacySQL\b", re.IGNORECASE)


def translate(sql: str, catalog: CatalogLookup) -> str:
    if _LEGACY_MARKERS.match(sql):
        raise UnsupportedSql("legacy SQL is not supported (use standard SQL)")
    _reject_unsupported_functions(sql)
    tree = cast(exp.Expression, sqlglot.parse_one(sql, read="bigquery"))
    tree = _rewrite_info_schema(tree)
    tree = _expand_wildcards(tree, catalog)
    tree = _rewrite_three_part_names(tree)
    tree = _rewrite_safe_prefix(tree)
    tree = _strip_partitioning(tree)
    return tree.sql(dialect="duckdb")


_BANNED = re.compile(
    r"(\bML\.[A-Z_]+\s*\(|\bST_[A-Z_]+\s*\(|\bDECLARE\b|\bBEGIN\b|\bEXCEPTION\b|\bFOR\s+SYSTEM_TIME\s+AS\s+OF\b)",
    re.IGNORECASE,
)


def _reject_unsupported_functions(sql: str) -> None:
    m = _BANNED.search(sql)
    if m:
        raise UnsupportedSql(f"unsupported feature in v1: {m.group(0).strip()}")


def _rewrite_three_part_names(tree: exp.Expression) -> exp.Expression:
    for tbl in tree.find_all(exp.Table):
        catalog = tbl.args.get("catalog")
        db = tbl.args.get("db")
        name = tbl.this
        if catalog is not None and db is not None and name is not None:
            project = catalog.name if isinstance(catalog, exp.Identifier) else str(catalog)
            dataset = db.name if isinstance(db, exp.Identifier) else str(db)
            schema_name = f"{project}:{dataset}"
            tbl.set("catalog", None)
            tbl.set("db", exp.to_identifier(schema_name, quoted=True))
            if isinstance(name, exp.Identifier):
                name.set("quoted", True)
    return tree


def _rewrite_safe_prefix(tree: exp.Expression) -> exp.Expression:
    # BigQuery's `SAFE.<fn>(...)` becomes `<fn>(...)` wrapped in DuckDB's TRY(...).
    # sqlglot may parse SAFE.<known_fn> as exp.SafeFunc(this=<fn>(...)) or
    # leave unknown functions as exp.Anonymous(this="SAFE.<fn>", ...).
    for safe_fn in list(tree.find_all(exp.SafeFunc)):
        inner = safe_fn.this
        wrapped = exp.Anonymous(this="TRY", expressions=[inner.copy()])
        safe_fn.replace(wrapped)
    for anon_fn in list(tree.find_all(exp.Anonymous)):
        name = anon_fn.name or ""
        if name.upper().startswith("SAFE."):
            inner_name = name.split(".", 1)[1]
            inner = exp.Anonymous(this=inner_name, expressions=anon_fn.expressions)
            wrapped = exp.Anonymous(this="TRY", expressions=[inner])
            anon_fn.replace(wrapped)
    return tree


def _expand_wildcards(tree: exp.Expression, catalog: CatalogLookup) -> exp.Expression:
    for tbl in list(tree.find_all(exp.Table)):
        name_node = tbl.this
        if not isinstance(name_node, exp.Identifier):
            continue
        if not name_node.name.endswith("*"):
            continue
        catalog_node = tbl.args.get("catalog")
        db_node = tbl.args.get("db")
        if catalog_node is None or db_node is None:
            continue
        project = (
            catalog_node.name if isinstance(catalog_node, exp.Identifier) else str(catalog_node)
        )
        dataset = db_node.name if isinstance(db_node, exp.Identifier) else str(db_node)
        prefix = name_node.name.rstrip("*")
        ids = [t for t in catalog.list_table_ids(project, dataset) if t.startswith(prefix)]
        if not ids:
            continue
        sub_sql = " UNION ALL ".join(f'SELECT * FROM "{project}:{dataset}"."{tid}"' for tid in ids)
        sub = cast(exp.Expression, sqlglot.parse_one(f"({sub_sql})", read="duckdb"))
        subquery = exp.Subquery(this=sub, alias=tbl.args.get("alias"))
        tbl.replace(subquery)
    return tree


def _rewrite_info_schema(tree: exp.Expression) -> exp.Expression:
    for tbl in list(tree.find_all(exp.Table)):
        if not isinstance(tbl.this, exp.Identifier):
            continue
        name = tbl.this.name
        if "." not in name or not name.upper().startswith("INFORMATION_SCHEMA."):
            # Also check the case where INFORMATION_SCHEMA is in `db` (some sqlglot versions)
            db = tbl.args.get("db")
            if (
                db is not None
                and isinstance(db, exp.Identifier)
                and db.name.upper() == "INFORMATION_SCHEMA"
            ):
                view = name
                catalog = tbl.args.get("catalog")
                dataset = catalog.name if isinstance(catalog, exp.Identifier) else None
                if dataset is None:
                    continue
                project = "_unknown"
            else:
                continue
        else:
            view = name.split(".", 1)[1]
            db = tbl.args.get("db")
            catalog = tbl.args.get("catalog")
            dataset = db.name if isinstance(db, exp.Identifier) else None
            project = catalog.name if isinstance(catalog, exp.Identifier) else "_unknown"
            if dataset is None:
                continue
        try:
            rewritten = rewrite_info_schema_reference(project, dataset, view)
        except UnsupportedInfoSchemaView as e:
            raise UnsupportedSql(str(e)) from None
        sub = cast(exp.Expression, sqlglot.parse_one(rewritten, read="duckdb"))
        tbl.replace(exp.Subquery(this=sub, alias=tbl.args.get("alias")))
    return tree


def _strip_partitioning(tree: exp.Expression) -> exp.Expression:
    for create in tree.find_all(exp.Create):
        props = create.args.get("properties")
        if props is None:
            continue
        kept = [
            p
            for p in props.expressions
            if not isinstance(p, exp.PartitionedByProperty | exp.Cluster)
        ]
        props.set("expressions", kept)
    return tree
