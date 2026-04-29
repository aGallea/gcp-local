"""Redelivery sweeper — periodically reclaims expired ack-leases.

A single sweeper handles all subscriptions in a service. The sweeper
runs every 1 second by default; tests can shorten the interval.
"""

import asyncio
import contextlib
import datetime as dt
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog

log = logging.getLogger(__name__)


class RedeliverySweeper:
    def __init__(
        self,
        *,
        backlogs: "dict[tuple[str, str], SubscriptionBacklog]",
        tick_interval: float = 1.0,
    ) -> None:
        self._backlogs = backlogs
        self._tick_interval = tick_interval
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="pubsub-redelivery-sweeper")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = dt.datetime.now(dt.UTC)
                for backlog in self._backlogs.values():
                    backlog.sweep_expired(now=now)
            except Exception:
                log.exception("pubsub redelivery sweeper error (continuing)")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_interval)
            except TimeoutError:
                continue
