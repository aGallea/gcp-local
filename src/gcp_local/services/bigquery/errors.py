"""BigQuery REST error envelope helper (spec §10)."""

from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse

from gcp_local.services.bigquery.names import InvalidName
from gcp_local.services.bigquery.storage import (
    DatasetAlreadyExists,
    DatasetNotFound,
    TableAlreadyExists,
    TableNotFound,
)
from gcp_local.services.bigquery.types import UnsupportedType


class JobNotFound(KeyError):
    pass


class InvalidQuery(ValueError):
    pass


class InvalidValue(ValueError):
    pass


_STATUS_MAP: list[tuple[type[Exception], int, str, str]] = [
    (DatasetNotFound, 404, "notFound", "NOT_FOUND"),
    (TableNotFound, 404, "notFound", "NOT_FOUND"),
    (JobNotFound, 404, "notFound", "NOT_FOUND"),
    (DatasetAlreadyExists, 409, "duplicate", "ALREADY_EXISTS"),
    (TableAlreadyExists, 409, "duplicate", "ALREADY_EXISTS"),
    (InvalidName, 400, "invalid", "INVALID_ARGUMENT"),
    (UnsupportedType, 400, "invalid", "INVALID_ARGUMENT"),
    (InvalidValue, 400, "invalid", "INVALID_ARGUMENT"),
    (InvalidQuery, 400, "invalidQuery", "INVALID_ARGUMENT"),
]


@dataclass
class _Resp:
    status_code: int
    body_dict: dict[str, Any]

    def to_response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status_code, content=self.body_dict)


def bigquery_error_response(exc: BaseException) -> _Resp:
    for cls, status, reason, status_str in _STATUS_MAP:
        if isinstance(exc, cls):
            return _build(status, str(exc) or cls.__name__, reason, status_str)
    return _build(500, str(exc) or "internal error", "internalError", "INTERNAL")


def _build(code: int, message: str, reason: str, status_str: str) -> _Resp:
    return _Resp(
        status_code=code,
        body_dict={
            "error": {
                "code": code,
                "message": message,
                "errors": [{"reason": reason, "message": message, "domain": "global"}],
                "status": status_str,
            }
        },
    )
