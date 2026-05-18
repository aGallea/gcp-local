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
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def reset_state(self) -> None:
        pass

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
