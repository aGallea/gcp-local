import contextlib
import logging
from pathlib import Path
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.generated.google.cloud.secretmanager.v1 import service_pb2_grpc
from gcp_local.services.secret_manager.servicer import SecretManagerServicer
from gcp_local.services.secret_manager.storage import (
    DiskStorage,
    InMemoryStorage,
    SecretManagerStorage,
)

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8086


class SecretManagerService:
    """Emulates Google Cloud Secret Manager over gRPC."""

    name = "secret_manager"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "grpc")]

    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._started = False
        self._storage: SecretManagerStorage | None = None

    async def start(self, ctx: Context) -> None:
        self._storage = self._make_storage(ctx)
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        servicer = SecretManagerServicer(storage=self._storage)
        service_pb2_grpc.add_SecretManagerServiceServicer_to_server(servicer, self._server)  # type: ignore[no-untyped-call]
        await self._server.start()
        self._started = True
        log.info("secret_manager service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.stop(grace=None)
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")

    def _make_storage(self, ctx: Context) -> SecretManagerStorage:
        if ctx.persist:
            root = Path(ctx.data_dir) / "secret_manager"
            root.mkdir(parents=True, exist_ok=True)
            return DiskStorage(root)
        return InMemoryStorage()
