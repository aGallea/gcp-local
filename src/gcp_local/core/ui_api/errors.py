"""Error envelope helpers for the internal ui-api.

The ui-api is consumed by the gcp-local browser UI only. Errors are returned
as ``{"error": {"code": str, "message": str}}`` and never leak stack traces,
filesystem paths, or secrets.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class UiApiError(Exception):
    """Raised by ui-api endpoints to produce a structured error response."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _envelope(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(UiApiError)
    async def _handle_known(_request: Request, exc: UiApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc.code, exc.message))

    @app.exception_handler(Exception)
    async def _handle_unknown(_request: Request, exc: Exception) -> JSONResponse:
        # Log the full exception for operators; return a generic message to clients.
        log.exception("ui-api internal error")
        return JSONResponse(
            status_code=500,
            content=_envelope("internal", "internal server error"),
        )
