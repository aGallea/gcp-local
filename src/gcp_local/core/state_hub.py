import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class StateHub:
    """In-process async pub/sub bus for cross-service events."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, event: dict) -> None:
        handlers = list(self._subs.get(topic, ()))
        if not handlers:
            return
        results = await asyncio.gather(
            *(self._safe(h, event) for h in handlers),
            return_exceptions=False,
        )
        del results

    async def _safe(self, handler: Handler, event: dict) -> None:
        try:
            await handler(event)
        except Exception:
            log.exception("state_hub handler raised for event %r", event)
