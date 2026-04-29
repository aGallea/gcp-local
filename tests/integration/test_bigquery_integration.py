"""Drive the emulator with the real google-cloud-bigquery client.

The google-cloud-bigquery client is synchronous (uses requests under the
hood).  Running sync BQ calls directly in an async test function blocks
the event loop and prevents the in-process uvicorn from serving the
requests.  Every call is therefore dispatched to a thread via
asyncio.get_running_loop().run_in_executor(None, fn).
"""

import asyncio
import io
import os
from collections.abc import Callable

import pytest
from google.api_core import exceptions as gax_exceptions
from google.auth import credentials as ga_credentials
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery, storage
from google.cloud.bigquery import (
    DatasetReference,
    SchemaField,
    TableReference,
)


async def _run[T](fn: Callable[[], T]) -> T:
    """Run a synchronous callable in the default thread executor."""
    return await asyncio.get_running_loop().run_in_executor(None, fn)


def _client(emulator: dict[str, int]) -> bigquery.Client:
    os.environ["BIGQUERY_EMULATOR_HOST"] = f"localhost:{emulator['bigquery_port']}"
    return bigquery.Client(
        project="test-project",
        credentials=ga_credentials.AnonymousCredentials(),
        client_options={"api_endpoint": f"http://localhost:{emulator['bigquery_port']}"},
    )


@pytest.mark.asyncio
async def test_dataset_crud(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ref = DatasetReference("test-project", "ds_crud")
    ds = bigquery.Dataset(ref)
    ds.labels = {"env": "dev"}
    await _run(lambda: client.create_dataset(ds))

    got = await _run(lambda: client.get_dataset(ref))
    assert got.labels == {"env": "dev"}

    got.description = "hello"
    await _run(lambda: client.update_dataset(got, ["description"]))
    updated = await _run(lambda: client.get_dataset(ref))
    assert updated.description == "hello"

    await _run(lambda: client.delete_dataset(ref))
    with pytest.raises(gax_exceptions.NotFound):
        await _run(lambda: client.get_dataset(ref))


@pytest.mark.asyncio
async def test_table_crud_with_struct_array(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    await _run(
        lambda: client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_t")))
    )
    schema = [
        SchemaField("id", "INT64", mode="REQUIRED"),
        SchemaField("tags", "STRING", mode="REPEATED"),
        SchemaField(
            "addr",
            "RECORD",
            mode="NULLABLE",
            fields=[
                SchemaField("city", "STRING"),
                SchemaField("zip", "STRING", mode="REQUIRED"),
            ],
        ),
    ]
    table = bigquery.Table(
        TableReference(DatasetReference("test-project", "ds_t"), "tbl"),
        schema=schema,
    )
    await _run(lambda: client.create_table(table))
    got = await _run(lambda: client.get_table(table.reference))
    assert [f.name for f in got.schema] == ["id", "tags", "addr"]


@pytest.mark.asyncio
async def test_streaming_insert_then_query(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    await _run(
        lambda: client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_si")))
    )
    schema = [
        SchemaField("id", "INT64", mode="REQUIRED"),
        SchemaField("name", "STRING"),
    ]
    table = await _run(
        lambda: client.create_table(
            bigquery.Table(
                TableReference(DatasetReference("test-project", "ds_si"), "rows"),
                schema=schema,
            )
        )
    )
    errors = await _run(
        lambda: client.insert_rows_json(table, [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
    )
    assert errors == []
    rows = await _run(
        lambda: list(
            client.query("SELECT id, name FROM `test-project.ds_si.rows` ORDER BY id").result()
        )
    )
    assert [(r["id"], r["name"]) for r in rows] == [(1, "a"), (2, "b")]


@pytest.mark.asyncio
async def test_dml_round_trip(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    await _run(
        lambda: client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_dml")))
    )
    schema = [SchemaField("id", "INT64", mode="REQUIRED")]
    await _run(
        lambda: client.create_table(
            bigquery.Table(
                TableReference(DatasetReference("test-project", "ds_dml"), "t"),
                schema=schema,
            )
        )
    )
    await _run(
        lambda: client.query("INSERT INTO `test-project.ds_dml.t` VALUES (1),(2),(3)").result()
    )
    await _run(lambda: client.query("UPDATE `test-project.ds_dml.t` SET id=99 WHERE id=2").result())
    await _run(lambda: client.query("DELETE FROM `test-project.ds_dml.t` WHERE id=3").result())
    rows = await _run(
        lambda: sorted(
            r["id"] for r in client.query("SELECT id FROM `test-project.ds_dml.t`").result()
        )
    )
    assert rows == [1, 99]


@pytest.mark.asyncio
async def test_paging_with_max_results(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    await _run(
        lambda: client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_pg")))
    )
    schema = [SchemaField("id", "INT64", mode="REQUIRED")]
    table = await _run(
        lambda: client.create_table(
            bigquery.Table(
                TableReference(DatasetReference("test-project", "ds_pg"), "t"),
                schema=schema,
            )
        )
    )
    await _run(lambda: client.insert_rows_json(table, [{"id": i} for i in range(10)]))
    rows = await _run(
        lambda: sorted(
            r["id"]
            for r in client.query("SELECT id FROM `test-project.ds_pg.t` ORDER BY id").result(
                page_size=4
            )
        )
    )
    assert rows == list(range(10))


@pytest.mark.asyncio
async def test_query_unknown_table_raises_not_found(
    emulator: dict[str, int],
) -> None:
    client = _client(emulator)
    with pytest.raises((gax_exceptions.NotFound, gax_exceptions.BadRequest)):
        await _run(
            lambda: client.query("SELECT * FROM `test-project.no_such_ds.no_such_t`").result()
        )


@pytest.mark.asyncio
async def test_query_parse_error_is_bad_request(
    emulator: dict[str, int],
) -> None:
    client = _client(emulator)
    with pytest.raises(gax_exceptions.BadRequest):
        await _run(lambda: client.query("SELECT FROM where").result())


@pytest.mark.asyncio
async def test_information_schema_tables(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    await _run(
        lambda: client.create_dataset(bigquery.Dataset(DatasetReference("test-project", "ds_is")))
    )
    await _run(
        lambda: client.create_table(
            bigquery.Table(
                TableReference(DatasetReference("test-project", "ds_is"), "alpha"),
                schema=[SchemaField("x", "INT64")],
            )
        )
    )
    rows = await _run(
        lambda: list(
            client.query(
                "SELECT table_name FROM `test-project.ds_is.INFORMATION_SCHEMA.TABLES` "
                "ORDER BY table_name"
            ).result()
        )
    )
    names = [r["table_name"] for r in rows]
    assert "alpha" in names


@pytest.mark.asyncio
async def test_jobs_list_includes_recent_job(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    await _run(lambda: client.query("SELECT 1").result())
    jobs = await _run(lambda: list(client.list_jobs(max_results=10)))
    assert any(j.state == "DONE" for j in jobs)


@pytest.mark.asyncio
async def test_load_table_from_json_explicit_schema(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_json")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "rows")
    schema = [
        SchemaField("id", "INT64", mode="REQUIRED"),
        SchemaField("name", "STRING"),
        SchemaField("payload", "JSON"),
    ]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    job_config = bigquery.LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON")
    rows = [{"id": i, "name": f"row-{i}", "payload": {"k": i}} for i in range(5)]
    job = await _run(lambda: client.load_table_from_json(rows, table_ref, job_config=job_config))
    await _run(lambda: job.result())
    out = await _run(
        lambda: list(
            client.query("SELECT count(*) AS c FROM `test-project.ds_load_json.rows`").result()
        )
    )
    assert out[0]["c"] == 5


@pytest.mark.asyncio
async def test_load_table_from_json_autodetect_creates_table(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_auto")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "auto_t")
    job_config = bigquery.LoadJobConfig(autodetect=True, source_format="NEWLINE_DELIMITED_JSON")
    rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    job = await _run(lambda: client.load_table_from_json(rows, table_ref, job_config=job_config))
    await _run(lambda: job.result())
    table = await _run(lambda: client.get_table(table_ref))
    by_name = {f.name: f.field_type for f in table.schema}
    # The client library normalizes INT64 to INTEGER on the way back out.
    assert by_name in (
        {"id": "INTEGER", "name": "STRING"},
        {"id": "INT64", "name": "STRING"},
    )


@pytest.mark.asyncio
async def test_load_table_from_file_csv(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_csv")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "csv_t")
    schema = [SchemaField("id", "INT64"), SchemaField("name", "STRING")]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="CSV",
        skip_leading_rows=1,
    )
    csv_text = "id,name\n1,alice\n2,bob\n"
    job = await _run(
        lambda: client.load_table_from_file(
            io.BytesIO(csv_text.encode()),
            table_ref,
            job_config=job_config,
        )
    )
    await _run(lambda: job.result())
    rows = await _run(
        lambda: list(
            client.query(
                "SELECT id, name FROM `test-project.ds_load_csv.csv_t` ORDER BY id"
            ).result()
        )
    )
    assert [(r["id"], r["name"]) for r in rows] == [(1, "alice"), (2, "bob")]


@pytest.mark.asyncio
async def test_load_table_write_truncate(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_trunc")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "trunc_t")
    schema = [SchemaField("id", "INT64")]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    # Pre-populate via insertAll.
    await _run(lambda: client.insert_rows_json(table_ref, [{"id": 99}, {"id": 100}]))
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="NEWLINE_DELIMITED_JSON",
        write_disposition="WRITE_TRUNCATE",
    )
    job = await _run(
        lambda: client.load_table_from_json([{"id": 1}], table_ref, job_config=job_config)
    )
    await _run(lambda: job.result())
    rows = await _run(
        lambda: list(client.query("SELECT id FROM `test-project.ds_load_trunc.trunc_t`").result())
    )
    assert [r["id"] for r in rows] == [1]


@pytest.mark.asyncio
async def test_load_table_write_empty_against_non_empty_fails(emulator: dict[str, int]) -> None:
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_we")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "we_t")
    schema = [SchemaField("id", "INT64")]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    await _run(lambda: client.insert_rows_json(table_ref, [{"id": 7}]))
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="NEWLINE_DELIMITED_JSON",
        write_disposition="WRITE_EMPTY",
    )
    with pytest.raises(gax_exceptions.GoogleAPICallError):
        job = await _run(
            lambda: client.load_table_from_json([{"id": 1}], table_ref, job_config=job_config)
        )
        await _run(lambda: job.result())


@pytest.mark.asyncio
async def test_load_table_resumable_large_payload(emulator: dict[str, int]) -> None:
    """Force the official client into resumable mode by sending ~6 MiB of NDJSON."""
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_big")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "big_t")
    schema = [SchemaField("id", "INT64"), SchemaField("blob", "STRING")]
    await _run(lambda: client.create_table(bigquery.Table(table_ref, schema=schema)))
    # ~6 MiB of NDJSON (each row ~250 B; 25_000 rows ≈ 6.2 MiB).
    big_blob = "x" * 240
    rows = [{"id": i, "blob": big_blob} for i in range(25_000)]
    job_config = bigquery.LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON")
    job = await _run(lambda: client.load_table_from_json(rows, table_ref, job_config=job_config))
    await _run(lambda: job.result())
    count = await _run(
        lambda: list(
            client.query("SELECT count(*) AS c FROM `test-project.ds_load_big.big_t`").result()
        )
    )
    assert count[0]["c"] == 25_000


def _gcs_client(emulator: dict[str, int]) -> storage.Client:
    # Don't touch STORAGE_EMULATOR_HOST here: the BigQuery service captures the
    # GCS endpoint from the environment at startup, so a stray env var leaking
    # between tests would point a freshly booted BQ at a dead GCS port from a
    # previous test's emulator. The api_endpoint client_option is enough.
    return storage.Client(
        project="test-project",
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": f"http://127.0.0.1:{emulator['gcs_port']}"},
    )


async def _upload(gcs: storage.Client, bucket_name: str, name: str, data: bytes) -> None:
    """Upload `data` to gs://bucket_name/name, creating the bucket if needed."""

    def _do() -> None:
        try:
            bucket = gcs.get_bucket(bucket_name)
        except gax_exceptions.NotFound:
            bucket = gcs.create_bucket(bucket_name)
        bucket.blob(name).upload_from_string(data)

    await _run(_do)


@pytest.mark.asyncio
async def test_load_table_from_uri_ndjson(emulator: dict[str, int]) -> None:
    bq = _client(emulator)
    gcs = _gcs_client(emulator)
    await _upload(gcs, "bq-load-src", "rows.ndjson", b'{"id":1,"name":"a"}\n{"id":2,"name":"b"}\n')
    ds_ref = DatasetReference("test-project", "ds_load_uri")
    await _run(lambda: bq.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "rows")
    schema = [SchemaField("id", "INT64"), SchemaField("name", "STRING")]
    job_config = bigquery.LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON")
    job = await _run(
        lambda: bq.load_table_from_uri(
            "gs://bq-load-src/rows.ndjson", table_ref, job_config=job_config
        )
    )
    await _run(lambda: job.result())
    out = await _run(
        lambda: list(
            bq.query("SELECT id, name FROM `test-project.ds_load_uri.rows` ORDER BY id").result()
        )
    )
    assert [(r["id"], r["name"]) for r in out] == [(1, "a"), (2, "b")]


@pytest.mark.asyncio
async def test_load_table_from_uri_glob_and_multi(emulator: dict[str, int]) -> None:
    bq = _client(emulator)
    gcs = _gcs_client(emulator)
    await _upload(gcs, "bq-glob", "part/a.ndjson", b'{"id":1}\n')
    await _upload(gcs, "bq-glob", "part/b.ndjson", b'{"id":2}\n')
    await _upload(gcs, "bq-glob", "part/c.ndjson", b'{"id":3}\n')
    await _upload(gcs, "bq-glob", "extra/d.ndjson", b'{"id":4}\n')
    ds_ref = DatasetReference("test-project", "ds_load_glob")
    await _run(lambda: bq.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "rows")
    schema = [SchemaField("id", "INT64")]
    job_config = bigquery.LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON")
    # Mix of glob + explicit URI exercises both code paths and dedupe.
    job = await _run(
        lambda: bq.load_table_from_uri(
            ["gs://bq-glob/part/*.ndjson", "gs://bq-glob/extra/d.ndjson"],
            table_ref,
            job_config=job_config,
        )
    )
    result = await _run(lambda: job.result())
    assert result.input_files == 4
    rows = await _run(
        lambda: list(
            bq.query("SELECT id FROM `test-project.ds_load_glob.rows` ORDER BY id").result()
        )
    )
    assert [r["id"] for r in rows] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_load_table_from_uri_csv(emulator: dict[str, int]) -> None:
    bq = _client(emulator)
    gcs = _gcs_client(emulator)
    await _upload(gcs, "bq-csv-src", "rows.csv", b"id,name\n1,alice\n2,bob\n")
    ds_ref = DatasetReference("test-project", "ds_load_uri_csv")
    await _run(lambda: bq.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "rows")
    schema = [SchemaField("id", "INT64"), SchemaField("name", "STRING")]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="CSV",
        skip_leading_rows=1,
    )
    job = await _run(
        lambda: bq.load_table_from_uri("gs://bq-csv-src/rows.csv", table_ref, job_config=job_config)
    )
    await _run(lambda: job.result())
    rows = await _run(
        lambda: list(
            bq.query(
                "SELECT id, name FROM `test-project.ds_load_uri_csv.rows` ORDER BY id"
            ).result()
        )
    )
    assert [(r["id"], r["name"]) for r in rows] == [(1, "alice"), (2, "bob")]


@pytest.mark.asyncio
async def test_load_table_from_uri_missing_object(emulator: dict[str, int]) -> None:
    bq = _client(emulator)
    gcs = _gcs_client(emulator)
    # Create the bucket so the failure is on the object, not the bucket.
    await _run(lambda: gcs.create_bucket("bq-miss"))
    ds_ref = DatasetReference("test-project", "ds_load_miss")
    await _run(lambda: bq.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "rows")
    schema = [SchemaField("id", "INT64")]
    job_config = bigquery.LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON")
    with pytest.raises(gax_exceptions.GoogleAPICallError):
        job = await _run(
            lambda: bq.load_table_from_uri(
                "gs://bq-miss/nope.ndjson", table_ref, job_config=job_config
            )
        )
        await _run(lambda: job.result())


@pytest.mark.asyncio
async def test_load_max_bad_records_and_ignore_unknown_values(emulator: dict[str, int]) -> None:
    """End-to-end: real BQ client wires LoadJobConfig flags through to the runner."""
    client = _client(emulator)
    ds_ref = DatasetReference("test-project", "ds_load_bad")
    await _run(lambda: client.create_dataset(bigquery.Dataset(ds_ref)))
    table_ref = TableReference(ds_ref, "rows")
    schema = [
        SchemaField("id", "INT64", mode="REQUIRED"),
        SchemaField("name", "STRING"),
    ]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format="NEWLINE_DELIMITED_JSON",
        max_bad_records=2,
        ignore_unknown_values=True,
    )
    rows = [
        {"id": 1, "name": "alice", "extra": "drop_me"},  # extra key stripped
        {"name": "missing_id"},  # bad-record (REQUIRED id missing)
        {"id": 2, "name": "bob"},
    ]
    job = await _run(lambda: client.load_table_from_json(rows, table_ref, job_config=job_config))
    result = await _run(lambda: job.result())
    # bad_records is exposed by the official client via output_bytes/job stats
    assert result.output_rows == 2
    out = await _run(
        lambda: list(
            client.query(
                "SELECT id, name FROM `test-project.ds_load_bad.rows` ORDER BY id"
            ).result()
        )
    )
    assert [(r["id"], r["name"]) for r in out] == [(1, "alice"), (2, "bob")]
