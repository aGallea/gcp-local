import grpc
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from gcp_local.core.errors import GcpError, GrpcError, rest_error_body
from gcp_local.services.gcs.operations import InvalidCompose
from gcp_local.services.gcs.preconditions import PreconditionFailed
from gcp_local.services.gcs.storage import BucketNotFound, ObjectCollision, ObjectNotFound


def error_response(code: int, reason: str, message: str) -> JSONResponse:
    err = GcpError(code=code, reason=reason, message=message)
    return JSONResponse(content=rest_error_body(err), status_code=code)


def http_exception(code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"reason": reason, "message": message},
    )


GRPC_MAPPED_ERRORS: tuple[type[Exception], ...] = (
    GrpcError,
    BucketNotFound,
    ObjectNotFound,
    PreconditionFailed,
    InvalidCompose,
    ObjectCollision,
)


def grpc_error_for(exc: Exception) -> GrpcError:
    if isinstance(exc, GrpcError):
        return exc
    if isinstance(exc, BucketNotFound):
        return GrpcError(grpc.StatusCode.NOT_FOUND, f"bucket {exc.args[0]!r} not found")
    if isinstance(exc, ObjectNotFound):
        return GrpcError(grpc.StatusCode.NOT_FOUND, f"object {exc.args[0]!r} not found")
    if isinstance(exc, PreconditionFailed):
        return GrpcError(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
    if isinstance(exc, InvalidCompose):
        return GrpcError(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    if isinstance(exc, ObjectCollision):
        return GrpcError(grpc.StatusCode.ALREADY_EXISTS, str(exc))
    raise TypeError(f"no gRPC status mapping for {type(exc).__name__}") from exc
