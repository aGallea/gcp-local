from dataclasses import dataclass
from typing import Any

import grpc

_HTTP_TO_STATUS: dict[int, str] = {
    400: "INVALID_ARGUMENT",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "ALREADY_EXISTS",
    412: "FAILED_PRECONDITION",
    429: "RESOURCE_EXHAUSTED",
    499: "CANCELLED",
    500: "INTERNAL",
    501: "UNIMPLEMENTED",
    503: "UNAVAILABLE",
    504: "DEADLINE_EXCEEDED",
}


@dataclass
class GcpError(Exception):
    code: int
    reason: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.reason}: {self.message}"


def rest_error_body(err: GcpError) -> dict[str, Any]:
    """Build the JSON body in the shape `google-api-core` expects.

    Shape matches the `googleapiclient`-style error envelope:
    https://cloud.google.com/apis/design/errors
    """
    return {
        "error": {
            "code": err.code,
            "message": err.message,
            "errors": [
                {
                    "domain": "global",
                    "reason": err.reason,
                    "message": err.message,
                }
            ],
            "status": _HTTP_TO_STATUS.get(err.code, "UNKNOWN"),
        }
    }


@dataclass
class GrpcError(Exception):
    code: grpc.StatusCode
    message: str
    reason: str | None = None

    def __str__(self) -> str:
        return f"{self.code.name}: {self.message}"
