from fastapi import HTTPException
from fastapi.responses import JSONResponse

from gcp_local.core.errors import GcpError, rest_error_body


def error_response(code: int, reason: str, message: str) -> JSONResponse:
    err = GcpError(code=code, reason=reason, message=message)
    return JSONResponse(content=rest_error_body(err), status_code=code)


def http_exception(code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"reason": reason, "message": message},
    )
