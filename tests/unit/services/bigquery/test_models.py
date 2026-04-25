from gcp_local.services.bigquery.models import (
    DatasetRecord,
    FieldSchema,
    JobRecord,
    TableRecord,
    dataset_from_dict,
    dataset_to_dict,
    job_from_dict,
    job_to_dict,
    table_from_dict,
    table_to_dict,
)


def test_dataset_round_trip() -> None:
    rec = DatasetRecord(
        project="p",
        dataset_id="d",
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description=None,
        labels={"env": "dev"},
        location="US",
        default_table_expiration_ms=None,
    )
    payload = dataset_to_dict(rec)
    assert payload["labels"] == {"env": "dev"}
    rec2 = dataset_from_dict(payload)
    assert rec2 == rec


def test_table_round_trip_with_struct_schema() -> None:
    schema = [
        FieldSchema(name="id", type="INT64", mode="REQUIRED", fields=None),
        FieldSchema(
            name="addr",
            type="RECORD",
            mode="NULLABLE",
            fields=[FieldSchema(name="city", type="STRING", mode="NULLABLE", fields=None)],
        ),
    ]
    rec = TableRecord(
        project="p",
        dataset_id="d",
        table_id="t",
        schema=schema,
        create_time="2026-04-25T00:00:00Z",
        last_modified_time="2026-04-25T00:00:00Z",
        description="hi",
        labels={},
        time_partitioning=None,
        range_partitioning=None,
        clustering=None,
    )
    payload = table_to_dict(rec)
    rec2 = table_from_dict(payload)
    assert rec2 == rec


def test_job_round_trip() -> None:
    rec = JobRecord(
        project="p",
        job_id="j1",
        job_type="QUERY",
        state="DONE",
        create_time="2026-04-25T00:00:00Z",
        start_time="2026-04-25T00:00:00Z",
        end_time="2026-04-25T00:00:00Z",
        user_email="local@gcp-local.invalid",
        statement_type="SELECT",
        sql="SELECT 1",
        destination_table=("_gcp_local", "_gcp_local_jobs", "_job_j1"),
        total_rows=1,
        total_bytes_processed=0,
        error_result=None,
        errors=[],
    )
    payload = job_to_dict(rec)
    assert payload["destination_table"] == ["_gcp_local", "_gcp_local_jobs", "_job_j1"]
    rec2 = job_from_dict(payload)
    assert rec2 == rec
