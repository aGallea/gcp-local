"""REST handlers for /bigquery/v2/projects/{project}/datasets/*."""

from typing import Any

from fastapi import APIRouter, Body, Path, Response

from gcp_local.services.bigquery.engine._time import now_epoch_ms_str
from gcp_local.services.bigquery.errors import (
    InvalidValue,
    bigquery_error_response,
)
from gcp_local.services.bigquery.models import DatasetRecord
from gcp_local.services.bigquery.names import (
    InvalidName,
    validate_dataset_id,
    validate_project_id,
)
from gcp_local.services.bigquery.storage import (
    BigQueryStorage,
    DatasetAlreadyExists,
    DatasetNotFound,
)


def _to_api(rec: DatasetRecord) -> dict[str, Any]:
    return {
        "kind": "bigquery#dataset",
        "id": f"{rec.project}:{rec.dataset_id}",
        "datasetReference": {
            "projectId": rec.project,
            "datasetId": rec.dataset_id,
        },
        "creationTime": rec.create_time,
        "lastModifiedTime": rec.last_modified_time,
        "description": rec.description,
        "labels": rec.labels,
        "location": rec.location,
        "defaultTableExpirationMs": rec.default_table_expiration_ms,
    }


def build_router(storage: BigQueryStorage) -> APIRouter:
    router = APIRouter(prefix="/bigquery/v2/projects")

    @router.post("/{project}/datasets")
    async def insert_dataset(
        project: str = Path(...),
        body: dict[str, Any] = Body(...),  # noqa: B008
    ) -> Any:
        try:
            validate_project_id(project)
            ref = body.get("datasetReference") or {}
            dataset_id = ref.get("datasetId") or ""
            if ref.get("projectId") and ref["projectId"] != project:
                raise InvalidValue(
                    f"datasetReference.projectId {ref['projectId']!r} != {project!r}"
                )
            validate_dataset_id(dataset_id)
            now = now_epoch_ms_str()
            rec = DatasetRecord(
                project=project,
                dataset_id=dataset_id,
                create_time=now,
                last_modified_time=now,
                description=body.get("description"),
                labels=dict(body.get("labels") or {}),
                location=body.get("location") or "US",
                default_table_expiration_ms=body.get("defaultTableExpirationMs"),
            )
            await storage.create_dataset(rec)
            return _to_api(rec)
        except (DatasetAlreadyExists, InvalidName, InvalidValue) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/datasets/{dataset_id}")
    async def get_dataset(project: str, dataset_id: str) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            rec = await storage.get_dataset(project, dataset_id)
            return _to_api(rec)
        except (DatasetNotFound, InvalidName) as e:
            return bigquery_error_response(e).to_response()

    @router.get("/{project}/datasets")
    async def list_datasets(project: str) -> Any:
        try:
            validate_project_id(project)
            recs = await storage.list_datasets(project)
            return {
                "kind": "bigquery#datasetList",
                "datasets": [_to_api(r) for r in recs],
            }
        except InvalidName as e:
            return bigquery_error_response(e).to_response()

    @router.delete("/{project}/datasets/{dataset_id}", status_code=204, response_model=None)
    async def delete_dataset(
        project: str, dataset_id: str, deleteContents: bool = False
    ) -> Response:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            await storage.delete_dataset(project, dataset_id, delete_contents=deleteContents)
            return Response(status_code=204)
        except (DatasetNotFound, InvalidName, ValueError) as e:
            return bigquery_error_response(e).to_response()

    @router.patch("/{project}/datasets/{dataset_id}")
    @router.put("/{project}/datasets/{dataset_id}")
    async def patch_dataset(
        project: str,
        dataset_id: str,
        body: dict[str, Any] = Body(...),  # noqa: B008
    ) -> Any:
        try:
            validate_project_id(project)
            validate_dataset_id(dataset_id)
            rec = await storage.get_dataset(project, dataset_id)
            if "description" in body:
                rec.description = body["description"]
            if "labels" in body:
                rec.labels = dict(body["labels"] or {})
            if "defaultTableExpirationMs" in body:
                rec.default_table_expiration_ms = body["defaultTableExpirationMs"]
            rec.last_modified_time = now_epoch_ms_str()
            await storage.update_dataset(rec)
            return _to_api(rec)
        except (DatasetNotFound, InvalidName, InvalidValue) as e:
            return bigquery_error_response(e).to_response()

    return router
