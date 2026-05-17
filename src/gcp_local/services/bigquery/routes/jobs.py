"""REST handlers for /bigquery/v2/projects/{p}/{jobs,queries}/*."""

import uuid
from typing import Any

from fastapi import APIRouter, Body, Path

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.engine.loads import LoadRunner
from gcp_local.services.bigquery.errors import (
    JobNotFound,
    bigquery_error_response,
    make_error_response,
)
from gcp_local.services.bigquery.models import FieldSchema, JobRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_job_id,
    validate_project_id,
)
from gcp_local.services.bigquery.types import duckdb_value_to_bq_wire


def job_to_api(rec: JobRecord) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "bigquery#job",
        "id": f"{rec.project}:{rec.job_id}",
        "jobReference": {"projectId": rec.project, "jobId": rec.job_id},
        "user_email": rec.user_email,  # snake_case kept for backward-compat with existing tests
        "userEmail": rec.user_email,
        "configuration": {"jobType": rec.job_type},
        "status": {"state": rec.state},
        "statistics": {
            "startTime": rec.start_time,
            "endTime": rec.end_time,
            "creationTime": rec.create_time,
            "totalBytesProcessed": str(rec.total_bytes_processed),
        },
    }
    if rec.job_type == "LOAD":
        body["configuration"]["load"] = rec.load_config or {}
        body["statistics"]["load"] = rec.load_stats or {}
    else:
        body["configuration"]["query"] = {"query": rec.sql}
        body["statistics"]["query"] = {
            "totalBytesProcessed": str(rec.total_bytes_processed),
            "statementType": rec.statement_type,
        }
    if rec.error_result is not None:
        body["status"]["errorResult"] = rec.error_result
        body["status"]["errors"] = rec.errors
    # LOAD jobs carry destinationTable inside configuration.load (populated by
    # LoadRunner via load_config); only QUERY/DML attach it under configuration.query.
    if rec.destination_table is not None and rec.job_type != "LOAD":
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


_DEFAULT_PAGE_SIZE = 10000


async def _attach_page(
    payload: dict[str, Any],
    runner: JobRunner,
    job_id: str,
    *,
    page_size: int,
    page_token: str | None,
) -> None:
    """Attach result-page fields to a query response.

    `maxResults=0` is BigQuery's "poll for completion, don't return rows yet"
    convention. The real BigQuery REST API responds with the `schema` but
    neither `rows` nor `pageToken` in that case (see the `python-bigquery`
    source — class `QueryJob.result` notes "we're missing rows and there's no
    next page token"). The client library uses the absence of `rows` as the
    signal to refetch from scratch instead of treating the empty page as the
    first page of results. Emitting `rows: []` + a `pageToken` would
    otherwise confuse pagination (and on `to_dataframe()` would push the
    client onto the BigQuery Storage gRPC path, which the emulator does not
    implement — issue #34).
    """
    schema = await runner.schema_for(job_id)
    payload["schema"] = _schema_to_api(schema)
    if page_size == 0:
        return
    page = await runner.read_page(job_id, page_size=page_size, page_token=page_token)
    payload["rows"] = _rows_to_wire(page.rows, page.schema)
    if page.next_page_token is not None:
        payload["pageToken"] = page.next_page_token


def build_router(runner: JobRunner, load_runner: LoadRunner | None = None) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post("/{project}/jobs")
    async def insert_job(project: str, body: dict[str, Any] = Body(...)) -> Any:  # noqa: B008
        try:
            validate_project_id(project)
            ref = body.get("jobReference") or {}
            job_id = ref.get("jobId") or f"job_{uuid.uuid4().hex}"
            validate_job_id(job_id)
            configuration = body.get("configuration") or {}
            load_cfg = configuration.get("load")
            if load_cfg is not None:
                # Lazy import: avoids a top-level cycle with routes/uploads.py
                # (uploads imports job_to_api from this module).
                from gcp_local.services.bigquery.routes.uploads import run_load_job

                if load_runner is None:
                    return make_error_response(
                        500, "load runner not configured", reason="internalError"
                    )
                return await run_load_job(
                    project=project,
                    job_id=job_id,
                    load_config=load_cfg,
                    data=b"",
                    load_runner=load_runner,
                    runner=runner,
                )
            qcfg = configuration.get("query") or {}
            sql = qcfg.get("query") or ""
            rec = await runner.run_query(project=project, job_id=job_id, sql=sql)
            return job_to_api(rec)
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/jobs/{job_id}")
    async def get_job(project: str, job_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.get(project, job_id)
            return job_to_api(rec)
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/jobs")
    async def list_jobs(project: str) -> Any:
        try:
            validate_project_id(project)
            recs = await runner.list_jobs(project)
            return {
                "kind": "bigquery#jobList",
                "jobs": [job_to_api(r) for r in recs],
            }
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.post("/{project}/jobs/{job_id}/cancel")
    async def cancel_job(project: str, job_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.cancel(project, job_id)
            return {"kind": "bigquery#jobCancelResponse", "job": job_to_api(rec)}
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.post("/{project}/queries")
    async def query_sync(project: str, body: dict[str, Any] = Body(...)) -> Any:  # noqa: B008
        try:
            validate_project_id(project)
            sql = body.get("query") or ""
            raw_max = body.get("maxResults")
            # `maxResults=0` is the BigQuery convention for "poll for completion,
            # don't return rows yet" — distinct from "maxResults not provided".
            page_size = int(raw_max) if raw_max is not None else _DEFAULT_PAGE_SIZE
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
                await _attach_page(
                    payload, runner, rec.job_id, page_size=page_size, page_token=None
                )
            return payload
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/queries/{job_id}")
    async def get_query_results(
        project: str,
        job_id: str = Path(...),
        maxResults: int | None = None,
        pageToken: str | None = None,
    ) -> Any:
        try:
            validate_project_id(project)
            validate_job_id(job_id)
            rec = await runner.get(project, job_id)
            payload: dict[str, Any] = {
                "kind": "bigquery#getQueryResultsResponse",
                "jobReference": {"projectId": project, "jobId": job_id},
                "jobComplete": True,
                "totalRows": str(rec.total_rows),
            }
            if rec.error_result is not None:
                payload["errors"] = rec.errors
                return payload
            if rec.statement_type == "SELECT":
                page_size = maxResults if maxResults is not None else _DEFAULT_PAGE_SIZE
                await _attach_page(
                    payload, runner, job_id, page_size=page_size, page_token=pageToken
                )
            else:
                # DML — no rows to return
                payload["schema"] = {"fields": []}
                payload["rows"] = []
            return payload
        except (JobNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    return router
