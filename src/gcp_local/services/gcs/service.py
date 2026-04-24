import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import DiskStorage, GcsStorage, InMemoryStorage

log = logging.getLogger(__name__)

_DEFAULT_PORT = 4443


class GcsService:
    """Emulates Google Cloud Storage over a REST API."""

    name = "gcs"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._started = False
        self._ctx: Context | None = None
        self._storage: GcsStorage | None = None
        self._generations = GenerationCounter()

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._storage = self._make_storage(ctx)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = self._build_app()
        self._server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(self._server.serve(), name=f"{self.name}-server")
        self._started = True
        log.info("gcs service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()
        self._generations.reset_all()

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")

    def _make_storage(self, ctx: Context) -> GcsStorage:
        if ctx.persist:
            gcs_root = Path(ctx.data_dir) / "gcs"
            gcs_root.mkdir(parents=True, exist_ok=True)
            return DiskStorage(gcs_root)
        return InMemoryStorage()

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="gcp-local GCS", version="0.0.1")

        @app.get("/")
        async def root() -> dict[str, str]:
            return {"service": "gcs", "status": "ok"}

        assert self._storage is not None
        assert self._ctx is not None
        app.include_router(
            build_router(
                storage=self._storage,
                state_hub=self._ctx.state_hub,  # type: ignore[arg-type]
                generations=self._generations,
            )
        )
        return app
