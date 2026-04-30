"""Pub/Sub Service — owns the gRPC server lifecycle."""

import contextlib
import logging
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.generated.google.pubsub.v1 import pubsub_pb2_grpc
from gcp_local.services.pubsub.engine.delivery import RedeliverySweeper
from gcp_local.services.pubsub.servicer import (
    PublisherServicer,
    SubscriberServicer,
)
from gcp_local.services.pubsub.storage import InMemoryStorage, PubSubStorage

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8085


class PubSubService:
    """Emulates Google Cloud Pub/Sub over gRPC.

    Storage is in-memory only; ``persist=True`` is logged-and-ignored
    (Pub/Sub state is intentionally transient — see the v1 spec §6).
    """

    name = "pubsub"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "grpc")]

    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._started = False
        self._storage: PubSubStorage | None = None
        self._sweeper: RedeliverySweeper | None = None

    async def start(self, ctx: Context) -> None:
        if ctx.persist:
            log.info("pubsub: PERSIST=1 ignored — storage is in-memory only")
        self._storage = InMemoryStorage()
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        publisher = PublisherServicer(storage=self._storage, state_hub=ctx.state_hub)
        subscriber = SubscriberServicer(storage=self._storage, publisher=publisher)
        pubsub_pb2_grpc.add_PublisherServicer_to_server(publisher, self._server)  # type: ignore[no-untyped-call]
        pubsub_pb2_grpc.add_SubscriberServicer_to_server(subscriber, self._server)  # type: ignore[no-untyped-call]
        self._sweeper = RedeliverySweeper(backlogs=subscriber._backlogs)
        await self._sweeper.start()
        await self._server.start()
        self._started = True
        log.info("pubsub service listening on :%d", port)

    async def stop(self) -> None:
        if self._sweeper is not None:
            with contextlib.suppress(Exception):
                await self._sweeper.stop()
            self._sweeper = None
        if self._server is not None:
            with contextlib.suppress(Exception):
                # grace=0 force-cancels in-flight RPCs immediately. ``None``
                # would block indefinitely waiting for active StreamingPull
                # streams to finish — they don't on their own; the long-poll
                # only exits when the client cancels. CI saw a 1h hang here.
                await self._server.stop(grace=0)
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
