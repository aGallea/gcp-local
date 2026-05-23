"""Fake GCE metadata server.

Exposes /computeMetadata/v1/... endpoints that satisfy google-auth's
ComputeEngineCredentials path, so unmodified ADC client code can mint a
stub token and route subsequent calls to the rest of gcp-local.
"""

import asyncio
import logging
from typing import ClassVar

import uvicorn

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.metadata.app import build_app

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8091


class MetadataService:
    """Emulates the GCE metadata server."""

    name = "metadata"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        app = build_app()
        sock = ctx.sockets.get(self.name)
        if sock:
            port = sock.getsockname()[1]
            cfg = uvicorn.Config(app, log_level="info", access_log=False)
            serve_sockets = [sock]
        else:
            port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
            cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info", access_log=False)
            serve_sockets = None
        self._server = uvicorn.Server(cfg)
        self._server_task = asyncio.create_task(
            self._server.serve(sockets=serve_sockets), name=f"{self.name}-server"
        )
        self._started = True
        log.info(
            "metadata service listening on :%d (clients: set GCE_METADATA_HOST=<host>:%d)",
            port,
            port,
        )

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
        pass

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
