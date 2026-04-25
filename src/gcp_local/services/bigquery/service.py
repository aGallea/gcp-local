import asyncio
import logging
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.bigquery.app import build_app

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
        self._started = False

    async def start(self, ctx: Context) -> None:
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._app = build_app()
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
        self._started = False

    async def reset_state(self) -> None:
        # No state yet — added in Task 5.
        return

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
