import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import grpc
import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.generated.google.storage.v2 import storage_pb2_grpc
from gcp_local.services.gcs.grpc_servicer import StorageServicer
from gcp_local.services.gcs.ids import GenerationCounter
from gcp_local.services.gcs.routes import build_router
from gcp_local.services.gcs.storage import DiskStorage, GcsStorage, InMemoryStorage

log = logging.getLogger(__name__)

_REST_PORT = Port(4443, "rest")
_GRPC_PORT = Port(4444, "grpc", name="grpc")


class GcsService:
    """Emulates Google Cloud Storage over the JSON REST API and gRPC Storage v2."""

    name = "gcs"
    default_ports: ClassVar[list[Port]] = [_REST_PORT, _GRPC_PORT]

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._grpc_server: grpc.aio.Server | None = None
        self._started = False
        self._ctx: Context | None = None
        self._storage: GcsStorage | None = None
        self._generations = GenerationCounter()

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._storage = self._make_storage(ctx)
        if isinstance(self._storage, DiskStorage):
            await self._storage.gc_stale_sessions(max_age_seconds=7 * 86400)
        port = ctx.port_for(self.name, _REST_PORT)
        grpc_port = ctx.port_for(self.name, _GRPC_PORT)
        await self._start_grpc(grpc_port)
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
        log.info("gcs service listening on :%d (rest) and :%d (grpc)", port, grpc_port)

    async def _start_grpc(self, port: int) -> None:
        assert self._storage is not None
        assert self._ctx is not None
        # gRPC defaults to SO_REUSEPORT, which lets a second emulator share the port silently.
        self._grpc_server = grpc.aio.server(options=[("grpc.so_reuseport", 0)])
        self._grpc_server.add_insecure_port(f"[::]:{port}")
        servicer = StorageServicer(
            storage=self._storage,
            generations=self._generations,
            state_hub=self._ctx.state_hub,
        )
        storage_pb2_grpc.add_StorageServicer_to_server(servicer, self._grpc_server)  # type: ignore[no-untyped-call]
        await self._grpc_server.start()

    async def stop(self) -> None:
        if self._grpc_server is not None:
            try:
                await self._grpc_server.stop(grace=None)
            except Exception:
                log.exception("gcs grpc server failed to stop")
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

    @property
    def storage(self) -> GcsStorage:
        """The underlying storage backend.

        Exposed so the admin ui-api router can read/write GCS state without
        going through the wire-format REST or gRPC APIs. The wire surfaces
        and the ui-api therefore share a single source of truth.
        """
        if self._storage is None:
            raise RuntimeError("gcs service is not started")
        return self._storage

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
