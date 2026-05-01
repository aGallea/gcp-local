"""Tests for JsonDiskStorage: snapshot/reload round-trips and persistence semantics."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gcp_local.services.firestore.models import DocumentRecord, IndexRecord
from gcp_local.services.firestore.storage import JsonDiskStorage
from gcp_local.services.firestore.values import DocumentReference, GeoPoint

P, DB = "my-project", "(default)"
DB2 = "staging"


def _dt(s: str = "2026-05-01T12:00:00+00:00") -> datetime:
    return datetime.fromisoformat(s)


def _doc(
    path: str,
    fields: dict | None = None,
    *,
    project: str = P,
    database: str = DB,
    version: int = 1,
) -> DocumentRecord:
    now = _dt()
    return DocumentRecord(
        project=project,
        database=database,
        path=path,
        fields=fields or {"x": 1},
        create_time=now,
        update_time=now,
        version=version,
    )


# ---------------------------------------------------------------------------
# 1. Round-trip all Value kinds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_reload_all_value_kinds(tmp_path: Path) -> None:
    """All Firestore Python value kinds survive a snapshot→reload cycle."""
    ref = DocumentReference(project="proj", database="(default)", path="col/doc")
    geo = GeoPoint(lat=37.4, lng=-122.1)
    fields = {
        "null_field": None,
        "bool_true": True,
        "bool_false": False,
        "int_field": 42,
        "float_field": 3.14,
        "str_field": "hello",
        "bytes_field": b"\x00\xff\xfe",
        "dt_field": _dt(),
        "ref_field": ref,
        "geo_field": geo,
        "array_field": [1, "two", None, True],
        "map_field": {"a": 1, "b": b"raw"},
        "nan_field": float("nan"),
        "inf_pos": float("inf"),
        "inf_neg": float("-inf"),
    }
    s = JsonDiskStorage(state_dir=tmp_path)
    await s.put_document(_doc("col/d1", fields=fields))
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    rec = await s2.get_document(P, DB, "col/d1")

    assert rec.fields["null_field"] is None
    assert rec.fields["bool_true"] is True
    assert rec.fields["bool_false"] is False
    assert rec.fields["int_field"] == 42
    assert abs(rec.fields["float_field"] - 3.14) < 1e-9
    assert rec.fields["str_field"] == "hello"
    assert rec.fields["bytes_field"] == b"\x00\xff\xfe"
    assert rec.fields["dt_field"] == _dt()
    assert rec.fields["ref_field"] == ref
    assert rec.fields["geo_field"] == geo
    assert rec.fields["array_field"] == [1, "two", None, True]
    assert rec.fields["map_field"] == {"a": 1, "b": b"raw"}
    assert math.isnan(rec.fields["nan_field"])
    assert math.isinf(rec.fields["inf_pos"]) and rec.fields["inf_pos"] > 0
    assert math.isinf(rec.fields["inf_neg"]) and rec.fields["inf_neg"] < 0


# ---------------------------------------------------------------------------
# 2. Multiple documents in the same database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_reload_multiple_docs(tmp_path: Path) -> None:
    s = JsonDiskStorage(state_dir=tmp_path)
    await s.put_document(_doc("users/alice", fields={"name": "Alice"}))
    await s.put_document(_doc("users/bob", fields={"name": "Bob"}))
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    alice = await s2.get_document(P, DB, "users/alice")
    bob = await s2.get_document(P, DB, "users/bob")
    assert alice.fields["name"] == "Alice"
    assert bob.fields["name"] == "Bob"


# ---------------------------------------------------------------------------
# 3. Multi-database isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_database_isolation(tmp_path: Path) -> None:
    """Documents in (default) and staging live in separate files and don't bleed."""
    s = JsonDiskStorage(state_dir=tmp_path)
    await s.put_document(_doc("col/d1", fields={"db": "default"}, database=DB))
    await s.put_document(_doc("col/d1", fields={"db": "staging"}, database=DB2))
    await s.snapshot(P, DB)
    await s.snapshot(P, DB2)

    # Separate files must exist
    firestore_dir = tmp_path / "firestore"
    files = {f.name for f in firestore_dir.glob("*.json")}
    assert f"{P}__{DB}.json" in files
    assert f"{P}__{DB2}.json" in files

    s2 = JsonDiskStorage(state_dir=tmp_path)
    d_default = await s2.get_document(P, DB, "col/d1")
    d_staging = await s2.get_document(P, DB2, "col/d1")
    assert d_default.fields["db"] == "default"
    assert d_staging.fields["db"] == "staging"


# ---------------------------------------------------------------------------
# 4. Version counter recomputed on load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_version_counter_recomputed_on_load(tmp_path: Path) -> None:
    s = JsonDiskStorage(state_dir=tmp_path)
    await s.put_document(_doc("col/a", version=5))
    await s.put_document(_doc("col/b", version=12))
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    assert await s2.current_version(P, DB) == 12


# ---------------------------------------------------------------------------
# 5. Corrupt schema_version raises a clear error
# ---------------------------------------------------------------------------


def test_corrupt_schema_version_raises(tmp_path: Path) -> None:
    import json

    firestore_dir = tmp_path / "firestore"
    firestore_dir.mkdir(parents=True, exist_ok=True)
    bad_file = firestore_dir / f"{P}__{DB}.json"
    bad_file.write_text(
        json.dumps({"schema_version": 999, "documents": {}, "indexes": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unsupported Firestore state file schema version"):
        JsonDiskStorage(state_dir=tmp_path)


# ---------------------------------------------------------------------------
# 6. Indexes round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_indexes_round_trip(tmp_path: Path) -> None:
    s = JsonDiskStorage(state_dir=tmp_path)
    idx = IndexRecord(
        name=f"projects/{P}/databases/{DB}/collectionGroups/users/indexes/abc123",
        fields=[{"field_path": "name"}, {"field_path": "age"}],
        state="READY",
    )
    await s.put_index(P, DB, idx)
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    loaded = await s2.get_index(P, DB, idx.name)
    assert loaded is not None
    assert loaded.name == idx.name
    assert loaded.fields == idx.fields
    assert loaded.state == "READY"


# ---------------------------------------------------------------------------
# 7. Empty state_dir: load is a no-op; put_document works after
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_state_dir_load_is_noop(tmp_path: Path) -> None:
    """Loading from an empty directory succeeds and subsequent writes work."""
    s = JsonDiskStorage(state_dir=tmp_path)
    # No documents loaded — directory is empty
    from gcp_local.services.firestore.errors import DocumentNotFound

    with pytest.raises(DocumentNotFound):
        await s.get_document(P, DB, "col/missing")

    # Insert and snapshot — directory must now contain the file
    await s.put_document(_doc("col/new", fields={"ok": True}))
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    rec = await s2.get_document(P, DB, "col/new")
    assert rec.fields["ok"] is True


# ---------------------------------------------------------------------------
# 8. Reload after delete: the deleted doc is not reloaded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_after_delete(tmp_path: Path) -> None:
    s = JsonDiskStorage(state_dir=tmp_path)
    await s.put_document(_doc("col/to_delete"))
    await s.put_document(_doc("col/to_keep"))
    await s.snapshot(P, DB)

    # Delete one doc and snapshot again
    await s.delete_document(P, DB, "col/to_delete")
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    from gcp_local.services.firestore.errors import DocumentNotFound

    with pytest.raises(DocumentNotFound):
        await s2.get_document(P, DB, "col/to_delete")
    kept = await s2.get_document(P, DB, "col/to_keep")
    assert kept is not None


# ---------------------------------------------------------------------------
# 9. bytes round-trip with non-ASCII content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bytes_roundtrip_non_ascii(tmp_path: Path) -> None:
    payload = bytes(range(256))  # all byte values 0..255
    s = JsonDiskStorage(state_dir=tmp_path)
    await s.put_document(_doc("col/b", fields={"data": payload}))
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    rec = await s2.get_document(P, DB, "col/b")
    assert rec.fields["data"] == payload


# ---------------------------------------------------------------------------
# 10. datetime round-trip preserves UTC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_datetime_roundtrip_utc(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 1, 12, 34, 56, 789000, tzinfo=UTC)
    s = JsonDiskStorage(state_dir=tmp_path)
    await s.put_document(_doc("col/t", fields={"ts": ts}))
    await s.snapshot(P, DB)

    s2 = JsonDiskStorage(state_dir=tmp_path)
    rec = await s2.get_document(P, DB, "col/t")
    loaded_ts = rec.fields["ts"]
    assert loaded_ts == ts
    assert loaded_ts.tzinfo is not None
    # Must stay UTC-aware
    assert loaded_ts.utcoffset().total_seconds() == 0
