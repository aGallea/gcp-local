"""Push subscription pump — POSTs delivered messages to push_endpoint.

One PushPump instance per subscription whose ``push_config.push_endpoint``
is non-empty. The pump owns a background task that pulls one message at a
time from the existing :class:`SubscriptionBacklog`, POSTs the wrapped
JSON envelope to the endpoint, and acks (2xx) or NACKs (anything else).

Failure semantics piggy-back on the redelivery sweeper: a NACK calls
``modify_ack_deadline(ack_id, 0)`` which puts the message at the head of
the backlog's NACK queue, and the next pump tick redelivers it. A pump
crash leaves the lease in place; the sweeper reclaims it once the
ack-deadline expires.
"""

import asyncio
import base64
import contextlib
import datetime as dt
import logging
from collections.abc import Callable
from typing import Any

import httpx

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
from gcp_local.services.pubsub.models import MessageRecord

log = logging.getLogger(__name__)

_DEFAULT_POST_TIMEOUT_SECONDS = 30.0
_DEFAULT_IDLE_WAIT_SECONDS = 10.0


def _format_publish_time(ts: dt.datetime) -> str:
    """RFC3339 with trailing ``Z`` (real Pub/Sub format)."""
    if ts.microsecond:
        s = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond:06d}"
    else:
        s = ts.strftime("%Y-%m-%dT%H:%M:%S")
    return s + "Z"


def _build_envelope(msg: MessageRecord, subscription_name: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "data": base64.b64encode(msg.data).decode("ascii"),
        "messageId": msg.message_id,
        "publishTime": _format_publish_time(msg.publish_time),
    }
    if msg.attributes:
        body["attributes"] = dict(msg.attributes)
    if msg.ordering_key:
        body["orderingKey"] = msg.ordering_key
    return {"message": body, "subscription": subscription_name}


class PushPump:
    def __init__(
        self,
        *,
        subscription_name: str,
        push_endpoint: str,
        backlog: SubscriptionBacklog,
        get_messages: Callable[[], list[MessageRecord]],
        post_timeout_seconds: float = _DEFAULT_POST_TIMEOUT_SECONDS,
        idle_wait_seconds: float = _DEFAULT_IDLE_WAIT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.subscription_name = subscription_name
        self.push_endpoint = push_endpoint
        self._backlog = backlog
        self._get_messages = get_messages
        self._post_timeout = post_timeout_seconds
        self._idle_wait = idle_wait_seconds
        self._client = httpx.AsyncClient(transport=transport, timeout=post_timeout_seconds)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"pubsub-push-pump:{self.subscription_name}"
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        with contextlib.suppress(Exception):
            await self._client.aclose()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("pubsub push pump %s: unexpected error", self.subscription_name)
                await asyncio.sleep(0.1)

    async def _tick(self) -> None:
        delivered = await self._backlog.pull(
            messages=self._get_messages(),
            max_count=1,
            now=dt.datetime.now(dt.UTC),
        )
        if not delivered:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._backlog.deliverable.wait(), timeout=self._idle_wait)
            self._backlog.deliverable.clear()
            return
        d = delivered[0]
        ok = await self._post(d.message)
        if ok:
            await self._backlog.acknowledge([d.ack_id])
        else:
            await self._backlog.modify_ack_deadline([(d.ack_id, 0)])

    async def _post(self, msg: MessageRecord) -> bool:
        envelope = _build_envelope(msg, self.subscription_name)
        try:
            response = await self._client.post(
                self.push_endpoint,
                json=envelope,
                headers={"User-Agent": "gcp-local-pubsub-push/0"},
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            log.warning(
                "pubsub push %s -> %s: transport error %r — NACK",
                self.subscription_name,
                self.push_endpoint,
                e,
            )
            return False
        if 200 <= response.status_code < 300:
            return True
        log.warning(
            "pubsub push %s -> %s: status %d — NACK",
            self.subscription_name,
            self.push_endpoint,
            response.status_code,
        )
        return False
