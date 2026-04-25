"""REST handlers for /bigquery/v2/projects/{p}/{jobs,queries}/*."""

import uuid
from typing import Any

from fastapi import APIRouter, Body, Path

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.errors import JobNotFound, bigquery_error_response
from gcp_local.services.bigquery.models import FieldSchema, JobRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_job_id,
    validate_project_id,
)
from gcp_local.services.bigquery.types import duckdb_value_to_bq_wire


def _job_to_api(rec: JobRecord) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "bigquery#job",
        "id": f"{rec.project}:{rec.job_id}",
        "jobReference": {"projectId": rec.project, "jobId": rec.job_id},
        "user_email": rec.user_email,
        "configuration": {"query": {"query": rec.sql}, "jobType": rec.job_type},
        "status": {"state": rec.state},
        "statistics": {
            "startTime": rec.start_time,
            "endTime": rec.end_time,
            "creationTime": rec.create_time,
            "totalBytesProcessed": str(rec.total_bytes_processed),
            "query": {
                "totalBytesProcessed": str(rec.total_bytes_processed),
                "statementType": rec.statement_type,
            },
        },
    }
    if rec.error_result is not None:
        body["status"]["errorResult"] = rec.error_result
        body["status"]["errors"] = rec.errors
    if rec.destination_table is not None:
        body["configuration"]["query"]["destinationTable"] = {
            "projectId": rec.destination_table[0],
            "datasetId": rec.destination_table[1],
            "tableId": rec.destination_table[2],
        }
    return body


def _rows_to_wire(
    rows: list[tuple],  # type: ignore[type-arg]
    schema: list[FieldSchema],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        cells = [duckdb_value_to_bq_wire(v, schema[i]) for i, v in enumerate(row)]
        out.append({"f": cells})
    return out


def _schema_to_api(schema: list[FieldSchema]) -> dict[str, Any]:
    return {"fields": [{"name": f.name, "type": f.type, "mode": f.mode} for f in schema]}


def build_router(runner: JobRunner) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post("/{project}/jobs")
    async def insert_job(project: str, body: dict[str, Any] = Body(...)) -> Any:  # noqa: B008
        try:
            validate_project_id(project)
            ref = body.get("jobReference") or {}
            job_id = ref.get("jobId") or f"job_{uuid.uuid4().hex}"
            validate_job_id(job_id)
            qcfg = (body.get("configuration") or {}).get("query") or {}
            sql = qcfg.get("query") or ""
            rec = await runner.run_query(project=project, job_id=job_id, sql=sql)
            return _job_to_api(rec)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/jobs/{job_id}")
    async def get_job(project: str, job_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.get(project, job_id)
            return _job_to_api(rec)
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/jobs")
    async def list_jobs(project: str) -> Any:
        try:
            validate_project_id(project)
            recs = await runner.list_jobs(project)
            return {
                "kind": "bigquery#jobList",
                "jobs": [_job_to_api(r) for r in recs],
            }
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.post("/{project}/jobs/{job_id}/cancel")
    async def cancel_job(project: str, job_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.cancel(project, job_id)
            return {"kind": "bigquery#jobCancelResponse", "job": _job_to_api(rec)}
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.post("/{project}/queries")
    async def query_sync(project: str, body: dict[str, Any] = Body(...)) -> Any:  # noqa: B008
        try:
            validate_project_id(project)
            sql = body.get("query") or ""
            page_size = int(body.get("maxResults") or 10000)
            job_id = body.get("requestId") or f"job_{uuid.uuid4().hex}"
            validate_job_id(job_id)
            rec = await runner.run_query(project=project, job_id=job_id, sql=sql)
            payload: dict[str, Any] = {
                "kind": "bigquery#queryResponse",
                "jobReference": {"projectId": project, "jobId": rec.job_id},
                "jobComplete": True,
                "totalRows": str(rec.total_rows),
                "totalBytesProcessed": "0",
            }
            if rec.error_result is not None:
                payload["errors"] = rec.errors
                payload["jobComplete"] = True
                return payload
            if rec.statement_type == "SELECT":
                page = await runner.read_page(rec.job_id, page_size=page_size, page_token=None)
                payload["schema"] = _schema_to_api(page.schema)
                payload["rows"] = _rows_to_wire(page.rows, page.schema)
                if page.next_page_token is not None:
                    payload["pageToken"] = page.next_page_token
            return payload
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/queries/{job_id}")
    async def get_query_results(
        project: str,
        job_id: str = Path(...),
        maxResults: int = 10000,
        pageToken: str | None = None,
    ) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.get(project, job_id)
            page = await runner.read_page(job_id, page_size=maxResults, page_token=pageToken)
            payload: dict[str, Any] = {
                "kind": "bigquery#getQueryResultsResponse",
                "jobReference": {"projectId": project, "jobId": job_id},
                "jobComplete": True,
                "totalRows": str(rec.total_rows),
                "schema": _schema_to_api(page.schema),
                "rows": _rows_to_wire(page.rows, page.schema),
            }
            if page.next_page_token is not None:
                payload["pageToken"] = page.next_page_token
            return payload
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    return router
