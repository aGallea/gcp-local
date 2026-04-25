import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    TableRecord,
)
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetAlreadyExists,
    DatasetNotFound,
    TableAlreadyExists,
    TableNotFound,
)


def _ds(project: str = "p", dataset_id: str = "d") -> DatasetRecord:
    return DatasetRecord(
        project=project,
        dataset_id=dataset_id,
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={},
        location="US",
        default_table_expiration_ms=None,
    )


def _tbl(table_id: str = "t", schema: list[FieldSchema] | None = None) -> TableRecord:
    return TableRecord(
        project="p",
        dataset_id="d",
        table_id=table_id,
        schema=schema or [FieldSchema(name="x", type="INT64", mode="NULLABLE", fields=None)],
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={},
        time_partitioning=None,
        range_partitioning=None,
        clustering=None,
    )


@pytest.fixture
async def storage() -> BigQueryStorage:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    return BigQueryStorage(conn)


@pytest.mark.asyncio
async def test_dataset_create_get(storage: BigQueryStorage) -> None:
    rec = _ds()
    await storage.create_dataset(rec)
    got = await storage.get_dataset("p", "d")
    assert got == rec


@pytest.mark.asyncio
async def test_dataset_create_duplicate_raises(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    with pytest.raises(DatasetAlreadyExists):
        await storage.create_dataset(_ds())


@pytest.mark.asyncio
async def test_dataset_get_missing_raises(storage: BigQueryStorage) -> None:
    with pytest.raises(DatasetNotFound):
        await storage.get_dataset("p", "d")


@pytest.mark.asyncio
async def test_dataset_list(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds(dataset_id="a"))
    await storage.create_dataset(_ds(dataset_id="b"))
    listed = await storage.list_datasets("p")
    assert [d.dataset_id for d in listed] == ["a", "b"]


@pytest.mark.asyncio
async def test_dataset_update(storage: BigQueryStorage) -> None:
    rec = _ds()
    await storage.create_dataset(rec)
    rec.description = "hi"
    rec.labels = {"env": "dev"}
    await storage.update_dataset(rec)
    got = await storage.get_dataset("p", "d")
    assert got.description == "hi"
    assert got.labels == {"env": "dev"}


@pytest.mark.asyncio
async def test_dataset_delete_cascades_to_tables(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    await storage.delete_dataset("p", "d", delete_contents=True)
    with pytest.raises(DatasetNotFound):
        await storage.get_dataset("p", "d")


@pytest.mark.asyncio
async def test_dataset_delete_non_empty_without_flag_raises(
    storage: BigQueryStorage,
) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    with pytest.raises(ValueError, match="not empty"):
        await storage.delete_dataset("p", "d", delete_contents=False)


@pytest.mark.asyncio
async def test_table_create_get_creates_duckdb_table(
    storage: BigQueryStorage,
) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    got = await storage.get_table("p", "d", "t")
    assert got.table_id == "t"
    # DuckDB-side table exists in the project:dataset schema.
    rows = await storage.connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'p:d' ORDER BY table_name"
    )
    assert [r[0] for r in rows] == ["t"]


@pytest.mark.asyncio
async def test_table_create_duplicate_raises(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    with pytest.raises(TableAlreadyExists):
        await storage.create_table(_tbl())


@pytest.mark.asyncio
async def test_table_get_missing_raises(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    with pytest.raises(TableNotFound):
        await storage.get_table("p", "d", "t")


@pytest.mark.asyncio
async def test_table_list(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl(table_id="a"))
    await storage.create_table(_tbl(table_id="b"))
    listed = await storage.list_tables("p", "d")
    assert [t.table_id for t in listed] == ["a", "b"]


@pytest.mark.asyncio
async def test_table_delete_drops_duckdb_table(storage: BigQueryStorage) -> None:
    await storage.create_dataset(_ds())
    await storage.create_table(_tbl())
    await storage.delete_table("p", "d", "t")
    with pytest.raises(TableNotFound):
        await storage.get_table("p", "d", "t")
    rows = await storage.connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'p:d'"
    )
    assert rows == []
