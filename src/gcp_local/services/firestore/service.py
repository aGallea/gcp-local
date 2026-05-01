"""Firestore Service — owns the gRPC server lifecycle."""

import contextlib
import logging
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc
from gcp_local.generated.google.firestore.v1 import firestore_pb2_grpc
from gcp_local.services.firestore.engine.transactions import TransactionTtlSweeper
from gcp_local.services.firestore.servicer import (
    FirestoreAdminServicer,
    FirestoreServicer,
)
from gcp_local.services.firestore.storage import FirestoreStorage, InMemoryStorage, JsonDiskStorage

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8080


class FirestoreService:
    """Emulates Google Cloud Firestore (Native mode) over gRPC."""

    name = "firestore"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "grpc")]

    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._started = False
        self._storage: FirestoreStorage | None = None
        self._sweeper: TransactionTtlSweeper | None = None

    async def start(self, ctx: Context) -> None:
        if ctx.persist:
            self._storage = JsonDiskStorage(state_dir=ctx.data_dir)
        else:
            self._storage = InMemoryStorage()
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        firestore_servicer = FirestoreServicer(storage=self._storage, state_hub=ctx.state_hub)
        admin_servicer = FirestoreAdminServicer(storage=self._storage)
        firestore_pb2_grpc.add_FirestoreServicer_to_server(  # type: ignore[no-untyped-call]
            firestore_servicer, self._server
        )
        firestore_admin_pb2_grpc.add_FirestoreAdminServicer_to_server(  # type: ignore[no-untyped-call]
            admin_servicer, self._server
        )
        await self._server.start()
        self._sweeper = TransactionTtlSweeper(self._storage)
        await self._sweeper.start()
        self._started = True
        log.info("firestore service listening on :%d", port)

    async def stop(self) -> None:
        if self._sweeper is not None:
            with contextlib.suppress(Exception):
                await self._sweeper.stop()
            self._sweeper = None
        if self._server is not None:
            with contextlib.suppress(Exception):
                # grace=0 force-cancels in-flight RPCs immediately to avoid
                # hanging on long-lived streams during teardown.
                await self._server.stop(grace=0)
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
