"""JobRecord LOAD-type round-trip + API serialization (Task 2)."""

from gcp_local.services.bigquery.models import JobRecord, job_from_dict, job_to_dict
from gcp_local.services.bigquery.routes.jobs import _job_to_api


def _load_record(**overrides) -> JobRecord:
    base = dict(
        project="p",
        job_id="j1",
        job_type="LOAD",
        state="DONE",
        create_time="1000",
        start_time="1000",
        end_time="2000",
        user_email="local@gcp-local.invalid",
        statement_type="",
        sql="",
        destination_table=("p", "d", "t"),
        total_rows=3,
        total_bytes_processed=0,
        error_result=None,
        errors=[],
        load_config={
            "destinationTable": {"projectId": "p", "datasetId": "d", "tableId": "t"},
            "sourceFormat": "NEWLINE_DELIMITED_JSON",
            "writeDisposition": "WRITE_APPEND",
            "createDisposition": "CREATE_IF_NEEDED",
        },
        load_stats={
            "inputFiles": "1",
            "inputFileBytes": "120",
            "outputRows": "3",
            "outputBytes": "120",
            "badRecords": "0",
        },
    )
    base.update(overrides)
    return JobRecord(**base)


def test_job_record_load_round_trip() -> None:
    rec = _load_record()
    raw = job_to_dict(rec)
    assert raw["load_config"]["sourceFormat"] == "NEWLINE_DELIMITED_JSON"
    rec2 = job_from_dict(raw)
    assert rec2 == rec


def test_job_to_api_load_branches_configuration_and_statistics() -> None:
    rec = _load_record()
    body = _job_to_api(rec)
    assert body["configuration"]["jobType"] == "LOAD"
    assert body["configuration"]["load"]["sourceFormat"] == "NEWLINE_DELIMITED_JSON"
    assert "query" not in body["configuration"]
    assert body["statistics"]["load"]["outputRows"] == "3"
    assert "query" not in body["statistics"]
    # Destination table still attaches.
    assert body["configuration"]["load"]["destinationTable"]["tableId"] == "t"


def test_job_to_api_query_unchanged() -> None:
    rec = JobRecord(
        project="p",
        job_id="j2",
        job_type="QUERY",
        state="DONE",
        create_time="1000",
        start_time="1000",
        end_time="2000",
        user_email="local@gcp-local.invalid",
        statement_type="SELECT",
        sql="SELECT 1",
        destination_table=("_gcp_local", "_gcp_local_jobs", "_job_j2"),
        total_rows=0,
        total_bytes_processed=0,
        error_result=None,
        errors=[],
    )
    body = _job_to_api(rec)
    assert body["configuration"]["query"]["query"] == "SELECT 1"
    assert "load" not in body["configuration"]
    assert body["statistics"]["query"]["statementType"] == "SELECT"
    assert "load" not in body["statistics"]
