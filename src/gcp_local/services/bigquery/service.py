import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.bigquery.app import build_app
from gcp_local.services.bigquery.engine.connection import BigQueryConnection
from gcp_local.services.bigquery.storage import BigQueryStorage

log = logging.getLogger(__name__)

_DEFAULT_PORT = 9050


class BigQueryService:
    """Emulates Google BigQuery over a REST API."""

    name = "bigquery"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._connection: BigQueryConnection | None = None
        self._storage: BigQueryStorage | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        self._connection = self._make_connection(ctx)
        await self._connection.startup()
        self._storage = BigQueryStorage(self._connection)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = build_app(storage=self._storage)
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
        log.info("bigquery service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        if self._connection is not None:
            await self._connection.shutdown()
        self._started = False

    async def reset_state(self) -> None:
        if self._connection is not None:
            await self._connection.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")

    def _make_connection(self, ctx: Context) -> BigQueryConnection:
        if ctx.persist:
            db_path = Path(ctx.data_dir) / "bigquery.duckdb"
            return BigQueryConnection.on_disk(db_path)
        return BigQueryConnection.in_memory()
