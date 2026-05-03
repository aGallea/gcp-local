from fastapi import FastAPI
from fastapi.testclient import TestClient

from gcp_local.core.ui_api.errors import UiApiError, register_error_handlers


def _app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raises")
    def raises() -> None:
        raise UiApiError(status_code=404, code="not_found", message="missing")

    return app


def test_ui_api_error_returns_envelope() -> None:
    client = TestClient(_app())
    r = client.get("/raises")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "missing"}}


def test_unhandled_exception_returns_internal_envelope() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    # raise_server_exceptions=False is required because starlette's
    # ServerErrorMiddleware always re-raises after invoking the Exception
    # handler so test runners can see the original traceback. We assert on
    # the response the handler produces.
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal"
    assert "kaboom" not in body["error"]["message"]
