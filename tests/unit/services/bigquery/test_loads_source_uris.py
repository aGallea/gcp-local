"""LoadRunner sourceUris path: bytes come from the GCS fetcher, not inline."""

import pytest

from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.engine.gcs_uri import GcsUriError, GcsUriFetcher
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.models import DatasetRecord
from gcp_local.services.bigquery.storage import BigQueryStorage


class _StubFetcher(GcsUriFetcher):
    """In-memory fetcher: maps URIs to bytes without any HTTP."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        super().__init__(endpoint="http://stub")
        self._mapping = mapping
        self.last_call: list[str] | None = None

    async def fetch_concat(self, uris: list[str]) -> tuple[bytes, int]:
        self.last_call = list(uris)
        if not uris:
            raise GcsUriError("empty")
        chunks: list[bytes] = []
        for u in uris:
            if u not in self._mapping:
                raise GcsUriError(f"object not found: {u}")
            chunks.append(self._mapping[u])
        return b"".join(chunks), len(uris)


async def _make_runner(fetcher: GcsUriFetcher | None) -> tuple[LoadRunner, BigQueryConnection]:
    conn = BigQueryConnection.in_memory()
    await conn.startup()
    storage = BigQueryStorage(conn)
    await storage.create_dataset(
        DatasetRecord(
            project="p",
            dataset_id="d",
            create_time="0",
            last_modified_time="0",
            description=None,
            labels={},
            location="US",
            default_table_expiration_ms=None,
        )
    )
    return LoadRunner(connection=conn, storage=storage, gcs_fetcher=fetcher), conn


@pytest.fixture
async def stub() -> _StubFetcher:
    return _StubFetcher(
        {
            "gs://b/one.ndjson": b'{"id":1,"name":"a"}\n',
            "gs://b/two.ndjson": b'{"id":2,"name":"b"}\n',
            "gs://b/rows.csv": b"id,name\n3,c\n4,d\n",
        }
    )


@pytest.mark.asyncio
async def test_source_uris_ndjson_reports_input_files(stub: _StubFetcher) -> None:
    runner, conn = await _make_runner(stub)
    try:
        config = {
            "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_uri"},
            "sourceFormat": "NEWLINE_DELIMITED_JSON",
            "sourceUris": ["gs://b/one.ndjson", "gs://b/two.ndjson"],
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64"},
                    {"name": "name", "type": "STRING"},
                ]
            },
        }
        rec = await runner.run_load(project="p", job_id="j_uri", load_config=config)
        assert rec.error_result is None
        assert rec.total_rows == 2
        # inputFiles tracks the count returned by the fetcher, not a hard-coded "1".
        assert rec.load_stats["inputFiles"] == "2"
        assert stub.last_call == ["gs://b/one.ndjson", "gs://b/two.ndjson"]
    finally:
        await conn.shutdown()


@pytest.mark.asyncio
async def test_source_uris_csv(stub: _StubFetcher) -> None:
    runner, conn = await _make_runner(stub)
    try:
        config = {
            "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_csv_uri"},
            "sourceFormat": "CSV",
            "sourceUris": ["gs://b/rows.csv"],
            "skipLeadingRows": 1,
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64"},
                    {"name": "name", "type": "STRING"},
                ]
            },
        }
        rec = await runner.run_load(project="p", job_id="j_csv", load_config=config)
        assert rec.error_result is None
        assert rec.total_rows == 2
    finally:
        await conn.shutdown()


@pytest.mark.asyncio
async def test_source_uris_without_fetcher_fails_invalid() -> None:
    runner, conn = await _make_runner(None)
    try:
        config = {
            "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_nofetch"},
            "sourceFormat": "NEWLINE_DELIMITED_JSON",
            "sourceUris": ["gs://b/one.ndjson"],
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        }
        rec = await runner.run_load(project="p", job_id="j_nf", load_config=config)
        assert rec.error_result is not None
        assert rec.error_result["reason"] == "invalid"
        assert "fetcher" in rec.error_result["message"].lower()
    finally:
        await conn.shutdown()


@pytest.mark.asyncio
async def test_source_uris_fetch_error_maps_to_invalid(stub: _StubFetcher) -> None:
    runner, conn = await _make_runner(stub)
    try:
        config = {
            "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t_miss"},
            "sourceFormat": "NEWLINE_DELIMITED_JSON",
            "sourceUris": ["gs://b/missing.ndjson"],
            "schema": {"fields": [{"name": "id", "type": "INT64"}]},
        }
        rec = await runner.run_load(project="p", job_id="j_miss", load_config=config)
        assert rec.error_result is not None
        assert rec.error_result["reason"] == "invalid"
    finally:
        await conn.shutdown()
