from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from gcp_local.core.lifecycle import Lifecycle


def build_admin_app(lc: Lifecycle) -> FastAPI:
    app = FastAPI(title="gcp-local admin API", version="0.0.1")

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

    return app
