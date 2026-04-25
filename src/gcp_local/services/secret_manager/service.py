import contextlib
import logging
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8086


class SecretManagerService:
    """Emulates Google Cloud Secret Manager over gRPC."""

    name = "secret_manager"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "grpc")]

    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        # Servicer registration happens in Task 9. Server starts empty.
        await self._server.start()
        self._started = True
        log.info("secret_manager service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.stop(grace=None)
        self._started = False

    async def reset_state(self) -> None:
        # Storage wiring comes in Task 9.
        pass

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
