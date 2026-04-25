from gcp_local.services.bigquery.errors import bigquery_error_response
from gcp_local.services.bigquery.names import InvalidName
from gcp_local.services.bigquery.storage import (
    DatasetAlreadyExists,
    DatasetNotFound,
)
from gcp_local.services.bigquery.types import UnsupportedType


def test_not_found_envelope() -> None:
    resp = bigquery_error_response(DatasetNotFound("p:d"))
    assert resp.status_code == 404
    body = resp.body_dict
    assert body["error"]["code"] == 404
    assert body["error"]["status"] == "NOT_FOUND"
    assert body["error"]["errors"][0]["reason"] == "notFound"


def test_already_exists_envelope() -> None:
    resp = bigquery_error_response(DatasetAlreadyExists("p:d"))
    assert resp.status_code == 409
    assert resp.body_dict["error"]["errors"][0]["reason"] == "duplicate"


def test_invalid_name_envelope() -> None:
    resp = bigquery_error_response(InvalidName("BAD"))
    assert resp.status_code == 400
    assert resp.body_dict["error"]["errors"][0]["reason"] == "invalid"


def test_unsupported_type_envelope() -> None:
    resp = bigquery_error_response(UnsupportedType("GEOGRAPHY"))
    assert resp.status_code == 400
    assert resp.body_dict["error"]["errors"][0]["reason"] == "invalid"


def test_uncaught_envelope() -> None:
    resp = bigquery_error_response(RuntimeError("boom"))
    assert resp.status_code == 500
    assert resp.body_dict["error"]["errors"][0]["reason"] == "internalError"
