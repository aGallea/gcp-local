"""FastAPI app for the fake GCE metadata server."""

import json as _json
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

_METADATA_FLAVOR_HEADER = "Metadata-Flavor"
_METADATA_FLAVOR_VALUE = "Google"

_DEFAULT_PROJECT_ID = "local-dev"
_DEFAULT_NUMERIC_PROJECT_ID = "0"
_DEFAULT_EMAIL = "default@local-dev.iam.gserviceaccount.com"
_DEFAULT_SCOPES = "https://www.googleapis.com/auth/cloud-platform"


def _project_id() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT") or _DEFAULT_PROJECT_ID


def _numeric_project_id() -> str:
    return os.environ.get("METADATA_NUMERIC_PROJECT_ID") or _DEFAULT_NUMERIC_PROJECT_ID


def _email() -> str:
    return os.environ.get("METADATA_SERVICE_ACCOUNT_EMAIL") or _DEFAULT_EMAIL


def _scopes() -> list[str]:
    raw = os.environ.get("METADATA_SCOPES") or _DEFAULT_SCOPES
    return [s.strip() for s in raw.split(",") if s.strip()]


def _resolve_alias(alias: str) -> str | None:
    """Return the canonical alias ('default') or None for an unknown alias."""
    if alias == "default" or alias == _email():
        return "default"
    return None


def _json_response(body: dict[str, object]) -> Response:
    """A JSONResponse-equivalent that doesn't strip middleware-added headers."""
    return Response(
        content=_json.dumps(body),
        media_type="application/json",
    )


class MetadataFlavorMiddleware(BaseHTTPMiddleware):
    """Enforce and echo the `Metadata-Flavor: Google` header.

    Real GCE returns 403 when a request omits this header (so a client can
    detect a fake server that doesn't enforce it). google-auth always sends
    it, and also checks that responses carry the same header in return.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get(_METADATA_FLAVOR_HEADER) != _METADATA_FLAVOR_VALUE:
            return PlainTextResponse(
                "Missing required Metadata-Flavor header.",
                status_code=403,
                headers={_METADATA_FLAVOR_HEADER: _METADATA_FLAVOR_VALUE},
            )
        response: Response = await call_next(request)
        response.headers[_METADATA_FLAVOR_HEADER] = _METADATA_FLAVOR_VALUE
        return response


def build_app() -> FastAPI:
    app = FastAPI(title="gcp-local metadata", version="0.0.1")
    app.add_middleware(MetadataFlavorMiddleware)

    @app.get("/", response_class=PlainTextResponse)
    async def _probe() -> str:
        return "computeMetadata/\n"

    @app.get("/computeMetadata/v1/project/project-id", response_class=PlainTextResponse)
    async def _project_id_route() -> str:
        return _project_id()

    @app.get("/computeMetadata/v1/project/numeric-project-id", response_class=PlainTextResponse)
    async def _numeric_project_id_route() -> str:
        return _numeric_project_id()

    @app.get("/computeMetadata/v1/instance/service-accounts/", response_class=PlainTextResponse)
    async def _sa_listing() -> str:
        return f"default/\n{_email()}/\n"

    @app.get("/computeMetadata/v1/instance/service-accounts/{alias}/")
    async def _sa_recursive(alias: str, recursive: str | None = None) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        return _json_response(
            {
                "aliases": ["default"],
                "email": _email(),
                "scopes": _scopes(),
            }
        )

    @app.get(
        "/computeMetadata/v1/instance/service-accounts/{alias}/email",
        response_class=PlainTextResponse,
    )
    async def _sa_email(alias: str) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        return PlainTextResponse(_email())

    @app.get(
        "/computeMetadata/v1/instance/service-accounts/{alias}/scopes",
        response_class=PlainTextResponse,
    )
    async def _sa_scopes(alias: str) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        return PlainTextResponse("\n".join(_scopes()) + "\n")

    return app
