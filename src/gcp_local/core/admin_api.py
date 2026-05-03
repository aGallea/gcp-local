from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.errors import register_error_handlers
from gcp_local.core.ui_api.router import build_ui_api_router

_FALLBACK_HTML = """<!doctype html>
<html>
  <head><title>gcp-local UI</title></head>
  <body style="font-family: system-ui; padding: 32px;">
    <h1>gcp-local UI bundle not built</h1>
    <p>The browser UI ships as a built static bundle. Editable installs need to build it once:</p>
    <pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>
    <p>Then restart the emulator. The rest of the API works without the UI.</p>
  </body>
</html>
"""


def build_admin_app(lc: Lifecycle) -> FastAPI:
    app = FastAPI(title="gcp-local admin API", version="0.0.1")
    app.state.lifecycle = lc
    register_error_handlers(app)

    @app.get("/_emulator/health")
    async def health() -> JSONResponse:
        statuses = lc.health_all()
        overall = all(s.ok for s in statuses.values())
        return JSONResponse(
            {
                "ok": overall,
                "services": {
                    name: {"ok": s.ok, "message": s.message} for name, s in statuses.items()
                },
            }
        )

    @app.get("/_emulator/services")
    async def services() -> dict[str, Any]:
        return {
            "services": [
                {
                    "name": s.name,
                    "ports": [
                        {"number": p.number, "protocol": p.protocol} for p in s.default_ports
                    ],
                }
                for s in lc.services
            ]
        }

    @app.post("/_emulator/reset")
    async def reset(service: str | None = Query(default=None)) -> Response:
        if service is None:
            await lc.reset_all()
        else:
            try:
                await lc.reset(service)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"unknown service: {service}") from None
        return Response(status_code=204)

    app.include_router(build_ui_api_router(lc))
    _mount_ui(app)
    return app


def _mount_ui(app: FastAPI) -> None:
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    from gcp_local.ui import static_dir

    base = static_dir()
    index = base / "index.html"
    if not index.exists():

        @app.get("/ui/", response_class=HTMLResponse)
        async def _ui_fallback_root() -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)

        @app.get("/ui/{_path:path}", response_class=HTMLResponse)
        async def _ui_fallback_any(_path: str) -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)

        return

    app.mount("/ui", StaticFiles(directory=base, html=True), name="ui")
