"""FastAPI app for the fake GCE metadata server."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

_METADATA_FLAVOR_HEADER = "Metadata-Flavor"
_METADATA_FLAVOR_VALUE = "Google"


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

    return app
