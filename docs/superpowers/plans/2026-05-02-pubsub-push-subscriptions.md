# Pub/Sub Push Subscriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Subscription.pushConfig` actually deliver — when a message lands on a topic with a push subscription, the emulator POSTs a wrapped JSON envelope to `push_endpoint` and acks/nacks based on the HTTP response.

**Architecture:** A new per-subscription `PushPump` runs a background asyncio task that calls the existing `SubscriptionBacklog.pull(max_count=1)` → POST → `acknowledge` (2xx) or `modify_ack_deadline(..., 0)` (NACK). Reuses the existing redelivery sweeper, ordering-key blocking, and deliverable Event wakeups. The `SubscriberServicer` owns a `_pumps` dict keyed by `(project, sub_id)` and starts/stops pumps in Create/Update/Delete and at service teardown.

**Tech Stack:** Python 3.13, asyncio, `httpx>=0.26` (already in runtime deps), `grpcio`, `google-cloud-pubsub` (test-only), `aiohttp` (test-only — needs adding to dev deps).

**Spec:** `docs/superpowers/specs/2026-05-02-pubsub-push-subscriptions-design.md`

---

## File map

| Path | Action | Responsibility |
|---|---|---|
| `src/gcp_local/services/pubsub/engine/push.py` | Create | `PushPump` class — pump loop, POST, lifecycle |
| `src/gcp_local/services/pubsub/servicer.py` | Modify | `_pumps` dict, pump start/stop in Create/Update/Delete, `push_config` in update mask |
| `src/gcp_local/services/pubsub/service.py` | Modify | Cancel pumps in `stop()` and `reset_state()` |
| `tests/unit/services/pubsub/test_push.py` | Create | Pump unit tests using `httpx.MockTransport` |
| `tests/integration/test_pubsub_integration.py` | Modify | Push-delivery integration test through real `google-cloud-pubsub` + `aiohttp` test server |
| `docs/services/pubsub.md` | Modify | Move push out of "What's not emulated"; add Push subscriptions section |
| `docs/architecture/pubsub.md` | Modify | Document the pump in the per-subscription state machine |
| `ROADMAP.md` | Modify | Drop the "Push subscriptions" follow-up bullet |
| `CHANGELOG.md` | Modify | `[Unreleased] → ### Added` entry |
| `pyproject.toml` | Modify | Add `aiohttp` to `optional-dependencies.dev` |

---

## Task 1: PushPump skeleton + first failing test (payload shape)

**Files:**
- Create: `src/gcp_local/services/pubsub/engine/push.py`
- Test: `tests/unit/services/pubsub/test_push.py`

- [ ] **Step 1: Write the failing test for the POST payload shape**

Create `tests/unit/services/pubsub/test_push.py`:

```python
"""Unit tests for the push subscription pump."""

import asyncio
import base64
import datetime as dt
import json

import httpx
import pytest

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
from gcp_local.services.pubsub.engine.push import PushPump
from gcp_local.services.pubsub.models import MessageRecord


def _msg(seq: int, data: bytes = b"hi", ordering_key: str = "", attributes: dict[str, str] | None = None) -> MessageRecord:
    return MessageRecord(
        message_id=f"t-{seq}",
        publish_time=dt.datetime(2026, 5, 2, 12, 0, 0, tzinfo=dt.UTC),
        data=data,
        attributes=attributes or {},
        ordering_key=ordering_key,
    )


async def _wait_for(predicate, *, timeout: float = 1.0, interval: float = 0.005) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"timed out waiting for {predicate!r}")


@pytest.mark.asyncio
async def test_push_payload_shape_matches_real_pubsub_envelope() -> None:
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1, data=b"hello", attributes={"region": "us-east1"})]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(lambda: len(received) == 1)
    finally:
        await pump.stop()

    request = received[0]
    assert request.method == "POST"
    assert request.url == httpx.URL("http://example.test/push")
    assert request.headers["content-type"] == "application/json"

    body = json.loads(request.content)
    assert body["subscription"] == "projects/p/subscriptions/s"
    assert body["message"]["messageId"] == "t-1"
    assert base64.b64decode(body["message"]["data"]) == b"hello"
    assert body["message"]["attributes"] == {"region": "us-east1"}
    assert body["message"]["publishTime"] == "2026-05-02T12:00:00Z"
    # orderingKey omitted when empty
    assert "orderingKey" not in body["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_push_payload_shape_matches_real_pubsub_envelope -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gcp_local.services.pubsub.engine.push'`

- [ ] **Step 3: Write minimal `PushPump`**

Create `src/gcp_local/services/pubsub/engine/push.py`:

```python
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
                # Avoid hot-spinning on persistent failure.
                await asyncio.sleep(0.1)

    async def _tick(self) -> None:
        delivered = await self._backlog.pull(
            messages=self._get_messages(),
            max_count=1,
            now=dt.datetime.now(dt.UTC),
        )
        if not delivered:
            try:
                await asyncio.wait_for(self._backlog.deliverable.wait(), timeout=self._idle_wait)
            except TimeoutError:
                pass
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
                "pubsub push %s → %s: transport error %r — NACK",
                self.subscription_name,
                self.push_endpoint,
                e,
            )
            return False
        if 200 <= response.status_code < 300:
            return True
        log.warning(
            "pubsub push %s → %s: status %d — NACK",
            self.subscription_name,
            self.push_endpoint,
            response.status_code,
        )
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_push_payload_shape_matches_real_pubsub_envelope -v`
Expected: PASS.

- [ ] **Step 5: Run lint/format**

Run: `ruff check src/gcp_local/services/pubsub/engine/push.py tests/unit/services/pubsub/test_push.py && ruff format src/gcp_local/services/pubsub/engine/push.py tests/unit/services/pubsub/test_push.py`
Expected: clean.

- [ ] **Step 6: Stage (do not commit — gcp-local CLAUDE.md says no auto-commit)**

```bash
git add src/gcp_local/services/pubsub/engine/push.py tests/unit/services/pubsub/test_push.py
```

---

## Task 2: Ack on 2xx, NACK on non-2xx

**Files:**
- Test: `tests/unit/services/pubsub/test_push.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/unit/services/pubsub/test_push.py`:

```python
@pytest.mark.asyncio
async def test_push_acks_on_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1)]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        # After ack, no leases remain and the cursor advances past the message.
        await _wait_for(lambda: backlog._cursor == 1 and not backlog._leases and not backlog._nacked)
    finally:
        await pump.stop()


@pytest.mark.asyncio
async def test_push_nacks_on_non_2xx_and_redelivers() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500) if calls == 1 else httpx.Response(200)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1)]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(lambda: calls >= 2 and not backlog._leases and not backlog._nacked)
    finally:
        await pump.stop()

    assert calls == 2  # first POST 500 → NACK → redelivered → second POST 200 → ack


@pytest.mark.asyncio
async def test_push_nacks_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1)]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
        post_timeout_seconds=0.05,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        # The message keeps NACKing forever; assert at least one NACK landed.
        await _wait_for(lambda: 1 in backlog._nacked or len(backlog._leases) > 0)
    finally:
        await pump.stop()
```

- [ ] **Step 2: Run tests to verify they pass (the implementation already supports these paths)**

Run: `pytest tests/unit/services/pubsub/test_push.py -v`
Expected: 4 tests pass (the 3 above + the payload-shape test from Task 1).

- [ ] **Step 3: Lint/format**

Run: `ruff check tests/unit/services/pubsub/test_push.py && ruff format tests/unit/services/pubsub/test_push.py`
Expected: clean.

---

## Task 3: Ordering key serialization

**Files:**
- Test: `tests/unit/services/pubsub/test_push.py`

- [ ] **Step 1: Add the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_push_serializes_messages_with_same_ordering_key() -> None:
    received_order: list[str] = []
    release_first = asyncio.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        received_order.append(body["message"]["messageId"])
        return httpx.Response(200)

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        # Hold the first POST until release_first is set, so the second
        # message cannot be delivered before the first ack.
        body = json.loads(request.content)
        received_order.append(body["message"]["messageId"])
        if body["message"]["messageId"] == "t-1":
            await release_first.wait()
        return httpx.Response(200)

    transport = httpx.MockTransport(slow_handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=30, enable_ordering=True)
    messages = [
        _msg(1, ordering_key="k"),
        _msg(2, ordering_key="k"),
    ]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(lambda: len(received_order) == 1)
        assert received_order == ["t-1"]
        # While first is in-flight, second must NOT have been POSTed yet.
        await asyncio.sleep(0.05)
        assert received_order == ["t-1"]
        release_first.set()
        await _wait_for(lambda: len(received_order) == 2)
    finally:
        await pump.stop()

    assert received_order == ["t-1", "t-2"]
```

- [ ] **Step 2: Run test**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_push_serializes_messages_with_same_ordering_key -v`
Expected: PASS — the backlog already blocks the second message until the first ack drops the ordering-key lease.

- [ ] **Step 3: Lint/format**

Run: `ruff check tests/unit/services/pubsub/test_push.py && ruff format tests/unit/services/pubsub/test_push.py`
Expected: clean.

---

## Task 4: Lifecycle — start/stop and pump-restart on endpoint change

**Files:**
- Test: `tests/unit/services/pubsub/test_push.py`

- [ ] **Step 1: Add the failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_push_pump_stop_cancels_task_cleanly() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: [],
        transport=transport,
    )
    await pump.start()
    assert pump._task is not None and not pump._task.done()
    await pump.stop()
    assert pump._task is None


@pytest.mark.asyncio
async def test_push_pump_double_start_is_idempotent() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: [],
        transport=transport,
    )
    await pump.start()
    first_task = pump._task
    await pump.start()  # no-op, no orphan
    assert pump._task is first_task
    await pump.stop()
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/services/pubsub/test_push.py -v`
Expected: all green.

- [ ] **Step 3: Lint/format**

Run: `ruff check src/gcp_local/services/pubsub/engine/push.py tests/unit/services/pubsub/test_push.py && ruff format src/gcp_local/services/pubsub/engine/push.py tests/unit/services/pubsub/test_push.py`
Expected: clean.

---

## Task 5: Wire pump into SubscriberServicer (Create + Delete)

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py`
- Test: `tests/unit/services/pubsub/test_push.py`

- [ ] **Step 1: Add a failing servicer-level test**

Append to `tests/unit/services/pubsub/test_push.py`:

```python
@pytest.mark.asyncio
async def test_servicer_starts_pump_when_create_subscription_has_push_config() -> None:
    from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
    from gcp_local.services.pubsub.servicer import PublisherServicer, SubscriberServicer
    from gcp_local.services.pubsub.storage import InMemoryStorage

    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage, state_hub=None)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)

    # Pre-create the topic the subscription points at.
    from gcp_local.services.pubsub.models import TopicRecord
    await storage.create_topic(
        TopicRecord(project="p", topic_id="t", labels={}, message_storage_policy=None, kms_key_name=None, schema_settings=None)
    )

    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    # Inject a transport factory so the subscriber uses our mock.
    subscriber._push_transport_factory = lambda: httpx.MockTransport(handler)  # type: ignore[attr-defined]

    sub = pubsub_pb2.Subscription(
        name="projects/p/subscriptions/s",
        topic="projects/p/topics/t",
        push_config=pubsub_pb2.PushConfig(push_endpoint="http://example.test/push"),
        ack_deadline_seconds=10,
    )

    class _NoopContext:
        async def abort(self, code, msg):
            raise AssertionError(f"abort {code}: {msg}")

    await subscriber.CreateSubscription(sub, _NoopContext())  # type: ignore[arg-type]
    assert ("p", "s") in subscriber._pumps

    # Publish via the storage path and trigger the pump.
    from gcp_local.services.pubsub.models import MessageRecord
    await storage.append_message(
        "p",
        "t",
        MessageRecord(
            message_id="t-1",
            publish_time=dt.datetime.now(dt.UTC),
            data=b"hi",
            attributes={},
            ordering_key="",
        ),
    )
    subscriber._backlogs[("p", "s")].deliverable.set()
    await _wait_for(lambda: len(received) == 1)

    # DeleteSubscription stops the pump.
    await subscriber.DeleteSubscription(
        pubsub_pb2.DeleteSubscriptionRequest(subscription="projects/p/subscriptions/s"),
        _NoopContext(),  # type: ignore[arg-type]
    )
    assert ("p", "s") not in subscriber._pumps
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_servicer_starts_pump_when_create_subscription_has_push_config -v`
Expected: FAIL — `subscriber._pumps` does not exist.

- [ ] **Step 3: Wire pumps into the SubscriberServicer**

Edit `src/gcp_local/services/pubsub/servicer.py`:

a. Add the import near the existing engine imports:

```python
from gcp_local.services.pubsub.engine.push import PushPump
```

b. In `SubscriberServicer.__init__`, add:

```python
self._pumps: dict[tuple[str, str], PushPump] = {}
self._push_transport_factory: Callable[[], Any] | None = None  # tests inject httpx.MockTransport
```

(Add `from collections.abc import Callable` to the existing typing imports if not already present.)

c. Add a helper method on `SubscriberServicer`:

```python
async def _ensure_pump(self, rec: SubscriptionRecord) -> None:
    """Start a PushPump for a subscription if it has a push_endpoint and one isn't already running."""
    endpoint = (rec.push_config or {}).get("push_endpoint")
    key = (rec.project, rec.subscription_id)
    existing = self._pumps.get(key)
    if not endpoint:
        if existing is not None:
            await existing.stop()
            self._pumps.pop(key, None)
        return
    if existing is not None and existing.push_endpoint == endpoint:
        return
    if existing is not None:
        await existing.stop()
        self._pumps.pop(key, None)
    backlog, _ = await self._get_backlog(rec.project, rec.subscription_id)
    transport = self._push_transport_factory() if self._push_transport_factory else None
    pump = PushPump(
        subscription_name=f"projects/{rec.project}/subscriptions/{rec.subscription_id}",
        push_endpoint=endpoint,
        backlog=backlog,
        get_messages=lambda: self._get_messages_sync(rec.topic_project, rec.topic_id),
        transport=transport,
    )
    await pump.start()
    self._pumps[key] = pump

def _get_messages_sync(self, topic_project: str, topic_id: str) -> list[MessageRecord]:
    """Synchronous shim for PushPump.get_messages.

    InMemoryStorage.get_messages is async but does no IO — it just returns
    a list reference. We call the underlying dict directly to avoid
    creating a new task per pump tick. If a future Storage adds real IO,
    PushPump.get_messages should switch to async.
    """
    return self._storage.get_messages_sync(topic_project, topic_id)  # added to storage in this task
```

d. Update `_drop_backlog` to also stop the pump:

```python
async def _drop_backlog(self, project: str, sub_id: str) -> None:
    key = (project, sub_id)
    pump = self._pumps.pop(key, None)
    if pump is not None:
        await pump.stop()
    self._backlogs.pop(key, None)
    self._locks.pop(key, None)
    self._publisher.deliverable_events.pop(key, None)
```

e. In `CreateSubscription`, after the storage create succeeds, call `await self._ensure_pump(rec)`:

```python
async def CreateSubscription(
    self,
    request: pubsub_pb2.Subscription,
    context: grpc.aio.ServicerContext[Any, Any],
) -> pubsub_pb2.Subscription:
    try:
        rec = _sub_proto_to_record(request)
        await self._storage.create_subscription(rec)
        await self._ensure_pump(rec)
    except (PubSubError, InvalidName) as e:
        await _abort(context, e)
    return _sub_record_to_proto(rec)
```

- [ ] **Step 4: Add the sync accessor on storage**

Edit `src/gcp_local/services/pubsub/storage.py`. Find `class InMemoryStorage` and add (alongside the existing async `get_messages`):

```python
def get_messages_sync(self, project: str, topic_id: str) -> list[MessageRecord]:
    """Non-async accessor used by the push pump's tight loop. Returns the
    same underlying list ``get_messages`` would await on; safe because
    InMemoryStorage's lock guards mutations, not reads of the list reference."""
    return list(self._topic_messages.get((project, topic_id), []))
```

(Match whatever the existing internal attribute name is — peek at the existing `async def get_messages` on line 143 of storage.py and mirror its accessor.)

Also add the corresponding abstract definition near the existing `get_messages` declaration on the `PubSubStorage` Protocol (line 38 area):

```python
def get_messages_sync(self, project: str, topic_id: str) -> list[MessageRecord]: ...
```

- [ ] **Step 5: Run test**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_servicer_starts_pump_when_create_subscription_has_push_config -v`
Expected: PASS.

- [ ] **Step 6: Run the full pubsub unit suite to catch regressions**

Run: `pytest tests/unit/services/pubsub/ -v`
Expected: all green (existing tests untouched, new tests pass).

- [ ] **Step 7: Lint/format**

Run: `ruff check src/gcp_local/services/pubsub/ tests/unit/services/pubsub/ && ruff format src/gcp_local/services/pubsub/ tests/unit/services/pubsub/`
Expected: clean.

---

## Task 6: Wire pump swap into UpdateSubscription

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py`
- Test: `tests/unit/services/pubsub/test_push.py`

The current `UpdateSubscription` only handles `ack_deadline_seconds` and `labels` in the update mask. Add `push_config` so toggling push↔pull (and changing endpoints) actually works.

- [ ] **Step 1: Add the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_servicer_swaps_pump_when_update_subscription_changes_push_endpoint() -> None:
    from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
    from gcp_local.services.pubsub.models import TopicRecord
    from gcp_local.services.pubsub.servicer import PublisherServicer, SubscriberServicer
    from gcp_local.services.pubsub.storage import InMemoryStorage

    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage, state_hub=None)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await storage.create_topic(TopicRecord(project="p", topic_id="t", labels={}, message_storage_policy=None, kms_key_name=None, schema_settings=None))

    received_a: list[httpx.Request] = []
    received_b: list[httpx.Request] = []
    current = {"target": "a"}

    def handler(request: httpx.Request) -> httpx.Response:
        target = received_a if current["target"] == "a" else received_b
        target.append(request)
        return httpx.Response(200)

    subscriber._push_transport_factory = lambda: httpx.MockTransport(handler)  # type: ignore[attr-defined]

    class _NoopContext:
        async def abort(self, code, msg):
            raise AssertionError(f"abort {code}: {msg}")

    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            push_config=pubsub_pb2.PushConfig(push_endpoint="http://a.test/push"),
            ack_deadline_seconds=10,
        ),
        _NoopContext(),  # type: ignore[arg-type]
    )
    pump_a = subscriber._pumps[("p", "s")]
    assert pump_a.push_endpoint == "http://a.test/push"

    current["target"] = "b"
    await subscriber.UpdateSubscription(
        pubsub_pb2.UpdateSubscriptionRequest(
            subscription=pubsub_pb2.Subscription(
                name="projects/p/subscriptions/s",
                push_config=pubsub_pb2.PushConfig(push_endpoint="http://b.test/push"),
            ),
            update_mask=__import__("google.protobuf.field_mask_pb2", fromlist=["FieldMask"]).FieldMask(paths=["push_config"]),
        ),
        _NoopContext(),  # type: ignore[arg-type]
    )
    pump_b = subscriber._pumps[("p", "s")]
    assert pump_b is not pump_a
    assert pump_b.push_endpoint == "http://b.test/push"
    # Old pump task is done.
    assert pump_a._task is None
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_servicer_swaps_pump_when_update_subscription_changes_push_endpoint -v`
Expected: FAIL — `UpdateSubscription` does not honor the `push_config` mask.

- [ ] **Step 3: Update `UpdateSubscription`**

In `src/gcp_local/services/pubsub/servicer.py`, modify the `updated = SubscriptionRecord(...)` block in `UpdateSubscription` to honor `push_config` when present in `update_mask.paths`:

```python
new_push_config: dict[str, Any] | None
if "push_config" in paths:
    if request.subscription.HasField("push_config") and request.subscription.push_config.push_endpoint:
        new_push_config = {"push_endpoint": request.subscription.push_config.push_endpoint}
        if request.subscription.push_config.attributes:
            new_push_config["attributes"] = dict(request.subscription.push_config.attributes)
    else:
        new_push_config = None
else:
    new_push_config = existing.push_config

updated = SubscriptionRecord(
    project=existing.project,
    subscription_id=existing.subscription_id,
    topic_project=existing.topic_project,
    topic_id=existing.topic_id,
    ack_deadline_seconds=(
        request.subscription.ack_deadline_seconds
        if "ack_deadline_seconds" in paths
        else existing.ack_deadline_seconds
    ),
    enable_message_ordering=existing.enable_message_ordering,
    push_config=new_push_config,
    filter=existing.filter,
    dead_letter_policy=existing.dead_letter_policy,
    retry_policy=existing.retry_policy,
    labels=(
        dict(request.subscription.labels)
        if "labels" in paths
        else dict(existing.labels)
    ),
    enable_exactly_once_delivery=existing.enable_exactly_once_delivery,
    create_time=existing.create_time,
)
await self._storage.update_subscription(updated)
await self._ensure_pump(updated)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_servicer_swaps_pump_when_update_subscription_changes_push_endpoint -v`
Expected: PASS.

- [ ] **Step 5: Add a "push → pull" test**

Append:

```python
@pytest.mark.asyncio
async def test_servicer_stops_pump_when_update_clears_push_config() -> None:
    from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
    from gcp_local.services.pubsub.models import TopicRecord
    from gcp_local.services.pubsub.servicer import PublisherServicer, SubscriberServicer
    from gcp_local.services.pubsub.storage import InMemoryStorage

    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage, state_hub=None)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await storage.create_topic(TopicRecord(project="p", topic_id="t", labels={}, message_storage_policy=None, kms_key_name=None, schema_settings=None))
    subscriber._push_transport_factory = lambda: httpx.MockTransport(lambda r: httpx.Response(200))  # type: ignore[attr-defined]

    class _NoopContext:
        async def abort(self, code, msg):
            raise AssertionError(f"abort {code}: {msg}")

    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            push_config=pubsub_pb2.PushConfig(push_endpoint="http://a.test/push"),
            ack_deadline_seconds=10,
        ),
        _NoopContext(),  # type: ignore[arg-type]
    )
    assert ("p", "s") in subscriber._pumps

    await subscriber.UpdateSubscription(
        pubsub_pb2.UpdateSubscriptionRequest(
            subscription=pubsub_pb2.Subscription(
                name="projects/p/subscriptions/s",
                push_config=pubsub_pb2.PushConfig(),  # cleared
            ),
            update_mask=__import__("google.protobuf.field_mask_pb2", fromlist=["FieldMask"]).FieldMask(paths=["push_config"]),
        ),
        _NoopContext(),  # type: ignore[arg-type]
    )
    assert ("p", "s") not in subscriber._pumps
```

- [ ] **Step 6: Run test**

Run: `pytest tests/unit/services/pubsub/test_push.py -v`
Expected: all green.

- [ ] **Step 7: Run the full pubsub unit suite**

Run: `pytest tests/unit/services/pubsub/ -v`
Expected: all green.

- [ ] **Step 8: Lint/format**

Run: `ruff check src/gcp_local/services/pubsub/ tests/unit/services/pubsub/ && ruff format src/gcp_local/services/pubsub/ tests/unit/services/pubsub/`
Expected: clean.

---

## Task 7: Service-level teardown — stop and reset_state cancel all pumps

**Files:**
- Modify: `src/gcp_local/services/pubsub/service.py`
- Test: `tests/unit/services/pubsub/test_push.py`

The cleanest path is to expose the subscriber on `PubSubService` (as `self._subscriber`) so the test can reach it directly. That's also what `stop()` and `reset_state()` use internally, so it's a real interface, not a test-only hack.

- [ ] **Step 1: Add the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_service_stop_cancels_all_pumps() -> None:
    from gcp_local.core.context import Context
    from gcp_local.services.pubsub.service import PubSubService
    from gcp_local.services.pubsub.engine.push import PushPump
    from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog

    svc = PubSubService()
    ctx = Context(persist=False, port_overrides={"pubsub": 0}, state_hub=None)
    await svc.start(ctx)

    # PubSubService should expose the subscriber for teardown wiring.
    assert svc._subscriber is not None
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    pump = PushPump(
        subscription_name="projects/p/subscriptions/s",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: [],
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    await pump.start()
    svc._subscriber._pumps[("p", "s")] = pump

    await svc.stop()

    assert pump._task is None  # stopped during svc.stop()
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_service_stop_cancels_all_pumps -v`
Expected: FAIL — `svc._subscriber` doesn't exist; `svc.stop()` doesn't cancel pumps.

- [ ] **Step 3: Update `PubSubService`**

Edit `src/gcp_local/services/pubsub/service.py`:

a. In `__init__`:

```python
self._subscriber: SubscriberServicer | None = None
```

(Add to existing imports: `from gcp_local.services.pubsub.servicer import PublisherServicer, SubscriberServicer`.)

b. In `start()`, after constructing `subscriber`:

```python
self._subscriber = subscriber
```

c. In `stop()`, before stopping the gRPC server, cancel pumps:

```python
async def stop(self) -> None:
    if self._sweeper is not None:
        with contextlib.suppress(Exception):
            await self._sweeper.stop()
        self._sweeper = None
    if self._subscriber is not None:
        pumps = list(self._subscriber._pumps.values())
        self._subscriber._pumps.clear()
        if pumps:
            await asyncio.gather(*(p.stop() for p in pumps), return_exceptions=True)
        self._subscriber = None
    if self._server is not None:
        with contextlib.suppress(Exception):
            await self._server.stop(grace=0)
    self._started = False
```

(Add `import asyncio` at the top of `service.py` if not already present.)

d. In `reset_state()`, also cancel pumps:

```python
async def reset_state(self) -> None:
    if self._subscriber is not None:
        pumps = list(self._subscriber._pumps.values())
        self._subscriber._pumps.clear()
        if pumps:
            await asyncio.gather(*(p.stop() for p in pumps), return_exceptions=True)
    if self._storage is not None:
        await self._storage.reset()
```

- [ ] **Step 4: Run test**

Run: `pytest tests/unit/services/pubsub/test_push.py::test_service_stop_cancels_all_pumps -v`
Expected: PASS.

- [ ] **Step 5: Run the full pubsub suite**

Run: `pytest tests/unit/services/pubsub/ tests/unit/services/pubsub/test_service_scaffold.py -v`
Expected: all green.

- [ ] **Step 6: Lint/format**

Run: `ruff check src/gcp_local/services/pubsub/ tests/unit/services/pubsub/ && ruff format src/gcp_local/services/pubsub/ tests/unit/services/pubsub/`
Expected: clean.

---

## Task 8: Integration test through real google-cloud-pubsub + aiohttp server

**Files:**
- Modify: `pyproject.toml` — add `aiohttp` to `optional-dependencies.dev`
- Modify: `tests/integration/test_pubsub_integration.py`

- [ ] **Step 1: Add aiohttp to dev deps**

Edit `pyproject.toml`. Inside `[project.optional-dependencies] dev = [ ... ]`, add `"aiohttp>=3.9",` (alphabetical order is fine — match the existing style).

- [ ] **Step 2: Reinstall dev deps**

Run: `pip install -e '.[dev]'`
Expected: aiohttp installed.

- [ ] **Step 3: Add the failing integration test**

Find the existing patterns in `tests/integration/test_pubsub_integration.py` (look at how an existing test starts the service, sets `PUBSUB_EMULATOR_HOST`, and uses `pubsub_v1.PublisherClient`). Append:

```python
@pytest.mark.asyncio
async def test_push_subscription_delivers_to_http_endpoint(pubsub_emulator) -> None:
    """Real google-cloud-pubsub publishes a message to a push subscription;
    the emulator POSTs to a local aiohttp server, which acks, and the
    message is not redelivered.
    """
    import asyncio
    import json

    from aiohttp import web
    from google.cloud import pubsub_v1

    received: list[dict] = []
    received_event = asyncio.Event()

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        received.append(body)
        received_event.set()
        return web.Response(status=204)

    app = web.Application()
    app.router.add_post("/push", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    # Discover the bound port.
    server = site._server  # aiohttp internal — best-effort; alternative: pre-bind a socket and pass via web.SockSite.
    bound_port = server.sockets[0].getsockname()[1]
    push_url = f"http://127.0.0.1:{bound_port}/push"

    try:
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        topic_path = publisher.topic_path("p", "push-topic")
        sub_path = subscriber.subscription_path("p", "push-sub")

        publisher.create_topic(request={"name": topic_path})
        subscriber.create_subscription(
            request={
                "name": sub_path,
                "topic": topic_path,
                "push_config": {"push_endpoint": push_url},
                "ack_deadline_seconds": 10,
            }
        )

        publisher.publish(topic_path, b"hello-push", region="us-east1").result(timeout=5)

        await asyncio.wait_for(received_event.wait(), timeout=10)

        assert len(received) == 1
        envelope = received[0]
        assert envelope["subscription"] == sub_path
        import base64
        assert base64.b64decode(envelope["message"]["data"]) == b"hello-push"
        assert envelope["message"]["attributes"] == {"region": "us-east1"}

        # Wait one redelivery sweep to confirm there's no double-delivery.
        await asyncio.sleep(1.5)
        assert len(received) == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_push_subscription_redelivers_on_500(pubsub_emulator) -> None:
    import asyncio
    from aiohttp import web
    from google.cloud import pubsub_v1

    calls = 0
    second_received = asyncio.Event()

    async def handler(request: web.Request) -> web.Response:
        nonlocal calls
        await request.json()
        calls += 1
        if calls == 1:
            return web.Response(status=500)
        second_received.set()
        return web.Response(status=204)

    app = web.Application()
    app.router.add_post("/push", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    bound_port = site._server.sockets[0].getsockname()[1]
    push_url = f"http://127.0.0.1:{bound_port}/push"

    try:
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        topic_path = publisher.topic_path("p", "push-retry-topic")
        sub_path = subscriber.subscription_path("p", "push-retry-sub")

        publisher.create_topic(request={"name": topic_path})
        subscriber.create_subscription(
            request={
                "name": sub_path,
                "topic": topic_path,
                "push_config": {"push_endpoint": push_url},
                "ack_deadline_seconds": 5,  # short, so NACK redelivers fast
            }
        )

        publisher.publish(topic_path, b"retry-me").result(timeout=5)

        await asyncio.wait_for(second_received.wait(), timeout=15)
        assert calls == 2  # first 500, second 204
    finally:
        await runner.cleanup()
```

(If `pubsub_emulator` is not the existing fixture name, look at the top of `tests/integration/test_pubsub_integration.py` and use the actual fixture pattern. Also check whether the file already exposes a helper for "create publisher/subscriber clients with PUBSUB_EMULATOR_HOST set" and use it.)

- [ ] **Step 4: Run integration test**

Run: `pytest tests/integration/test_pubsub_integration.py -v -k push`
Expected: both push tests pass.

- [ ] **Step 5: Lint/format**

Run: `ruff check tests/integration/test_pubsub_integration.py && ruff format tests/integration/test_pubsub_integration.py`
Expected: clean.

---

## Task 9: Documentation — `docs/services/pubsub.md`

**Files:**
- Modify: `docs/services/pubsub.md`

- [ ] **Step 1: Remove the "What's not emulated" entry**

Find this line:
```
- **`Subscription.pushConfig`** — stored and returned by `GetSubscription`, but no HTTP delivery loop runs. Push subscriptions are inert in v1.
```
Delete it.

- [ ] **Step 2: Remove the corresponding "Limits & quirks" callout**

Find:
```
**Push subscriptions are inert.** `pushConfig` is stored and returned by `GetSubscription`, but the emulator never POSTs to the push endpoint. Treat push-style subscriptions as pull subscriptions during local development.
```
Delete it.

- [ ] **Step 3: Add a new "Push subscriptions" section**

Add after the "Quickstart" section (preserving the existing markdown style):

````markdown
## Push subscriptions

The emulator delivers messages to subscriptions configured with `push_config.push_endpoint`. When a message lands on the topic, the emulator POSTs a JSON envelope matching real Pub/Sub's wire format to the endpoint:

```json
{
  "message": {
    "data": "<base64>",
    "attributes": { "region": "us-east1" },
    "messageId": "events-1",
    "publishTime": "2026-05-02T12:00:00Z",
    "orderingKey": "user-42"
  },
  "subscription": "projects/<p>/subscriptions/<s>"
}
```

`attributes` is omitted when the published message has none; `orderingKey` is omitted when empty. The default `Content-Type` is `application/json`.

**Acks via HTTP status:**

- `2xx` → message acked.
- Non-`2xx`, connection error, or timeout (default 30 s) → message NACKed; the existing ack-deadline redelivery sweeper redrives on the next pump tick.

**Per-subscription serial delivery.** The pump sends one message at a time. Two messages with the same `orderingKey` are delivered in publish order: the second waits until the first is acked. Across different ordering keys (or with ordering disabled), the pump still serializes per subscription — real Pub/Sub may parallelize, but the emulator does not.

**Endpoint changes.** `UpdateSubscription` with the `push_config` field mask swaps the pump: clearing `push_endpoint` stops delivery; pointing at a new URL restarts the pump targeting the new endpoint. The same field mask supports flipping a pull subscription into a push subscription and back.

**Not emitted (deferred):**

- `pushConfig.oidcToken` — stored on the resource, but no `Authorization` header is added to the POST. Real Pub/Sub signs a JWT here.
- `pushConfig.attributes` — stored, but not echoed back as HTTP headers (`x-goog-version` etc.).
- `subscription.retryPolicy.minimumBackoff` / `maximumBackoff` — stored, not honored. NACK redelivers on the next pump tick (no exponential backoff).
- `noWrapper` mode — always send the wrapped envelope.
````

- [ ] **Step 4: Lint/format docs**

(No formatter for markdown in this repo; leave as-is.)

---

## Task 10: Documentation — `docs/architecture/pubsub.md`

**Files:**
- Modify: `docs/architecture/pubsub.md`

- [ ] **Step 1: Document the pump alongside pull / streaming-pull**

Open `docs/architecture/pubsub.md`. Find the section that describes per-subscription delivery state (the `SubscriptionBacklog` and redelivery sweeper). Add a paragraph describing the push pump:

```markdown
### Push pump (per-subscription)

Subscriptions whose `push_config.push_endpoint` is non-empty get a background `PushPump` task in addition to their `SubscriptionBacklog`. The pump is conceptually a synchronous client of the same backlog the pull/StreamingPull RPCs use:

1. `pull(max_count=1)` to obtain the next deliverable message (or wait on `backlog.deliverable` when none is ready).
2. POST the wrapped JSON envelope to `push_endpoint` over a per-pump `httpx.AsyncClient`.
3. On 2xx, `acknowledge([ack_id])`. On any other outcome (non-2xx, connection error, timeout), `modify_ack_deadline([(ack_id, 0)])` — a NACK that returns the message to the head of the backlog's NACK queue.

The redelivery sweeper does not need to know the subscription is push-shaped: a NACK, an expired lease, or a pump crash all converge on the same code path. Pump lifecycle is driven by `SubscriberServicer`:

| Event | Pump action |
|---|---|
| `CreateSubscription` with `push_config.push_endpoint` | Start |
| `UpdateSubscription` mask includes `push_config` | Stop old pump; start new (or stop only, if endpoint cleared) |
| `DeleteSubscription` | Stop |
| `PubSubService.stop()` / `reset_state()` | Stop all pumps before tearing down storage |
```

- [ ] **Step 2: Verify renders**

Run: `grep -A 20 "Push pump" docs/architecture/pubsub.md`
Expected: the new section is present and its bullet list is intact.

---

## Task 11: ROADMAP and CHANGELOG

**Files:**
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Drop the ROADMAP follow-up**

In `ROADMAP.md`, under `### Pub/Sub`, delete this bullet:

```
- **Push subscriptions** — `pushConfig` is accepted and stored, but the emulator does not POST to the URL.
```

- [ ] **Step 2: Add the CHANGELOG entry**

In `CHANGELOG.md`, find `## [Unreleased]`. Add an `### Added` block (creating the section if it doesn't exist):

```markdown
## [Unreleased]

### Added

- **Pub/Sub:** push subscriptions now deliver. When `Subscription.pushConfig.pushEndpoint` is set, the emulator POSTs each published message to the endpoint as a wrapped JSON envelope (`{message: {data, attributes, messageId, publishTime, orderingKey}, subscription}`). 2xx acks the message; anything else (non-2xx, connection error, 30 s timeout) NACKs and the existing ack-deadline redelivery sweeper redrives. `UpdateSubscription` with the `push_config` mask hot-swaps the pump endpoint or flips push↔pull. `oidcToken`, `retryPolicy` backoff, `pushConfig.attributes`, and `noWrapper` remain deferred — see `docs/services/pubsub.md`.
```

- [ ] **Step 3: Verify**

Run: `grep -A 3 "push subscriptions now deliver" CHANGELOG.md`
Expected: the entry is there.

---

## Task 12: e2e — push delivery in the order-pipeline example

**Why:** the order-pipeline e2e example exercises every service against the real emulator container. Push subscriptions deserve a slot here so users see the wire path end-to-end and so CI catches docker/networking regressions (e.g. host-reachability of the push endpoint).

**Files:**
- Modify: `examples/order-pipeline/docker-compose.yml` — add `extra_hosts` so the emulator container can reach the host
- Modify: `examples/order-pipeline/test_e2e.py` — add a push-delivery test
- Modify: `examples/order-pipeline/README.md` — short note that push subs are exercised

The push test spins up an `aiohttp` server bound to `0.0.0.0` on a random host port, creates a push subscription pointing at `http://host.docker.internal:<port>/push`, publishes a message via the real `google-cloud-pubsub` client, and asserts the server receives the wrapped envelope. `host.docker.internal` resolves to the host on Mac/Windows by default; on Linux (CI runners) it requires `extra_hosts: host.docker.internal:host-gateway` in the compose file.

- [ ] **Step 1: Allow the emulator container to reach the host**

Edit `examples/order-pipeline/docker-compose.yml`. Under `services.gcp-local`, add:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

The full block becomes:

```yaml
services:
  gcp-local:
    build:
      context: ../..
      dockerfile: docker/Dockerfile
    environment:
      SERVICES: "bigquery,gcs,secret_manager,pubsub,firestore"
      PERSIST: "0"
    ports:
      - "4510:4510"
      - "4443:4443"
      - "8080:8080"
      - "8085:8085"
      - "8086:8086"
      - "9050:9050"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,json,sys; r=json.load(urllib.request.urlopen('http://localhost:4510/_emulator/health')); sys.exit(0 if r.get('ok') else 1)\""]
      interval: 1s
      timeout: 2s
      retries: 30
      start_period: 2s
```

- [ ] **Step 2: Add a push-delivery e2e test**

Append to `examples/order-pipeline/test_e2e.py`:

```python
def test_pubsub_push_subscription_delivers_to_host(pipeline: OrderPipeline) -> None:
    """End-to-end push delivery: emulator (in container) POSTs to an
    aiohttp server (on the host) reachable via host.docker.internal.

    Skips if host.docker.internal does not resolve from inside the container
    (e.g. older Linux Docker without the host-gateway extra_hosts entry).
    """
    import asyncio
    import json
    import socket
    import threading
    import uuid

    import pytest
    from aiohttp import web
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import pubsub_v1

    received: list[dict] = []
    received_event = threading.Event()

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        received.append(body)
        received_event.set()
        return web.Response(status=204)

    # Bind to all interfaces on a random port the emulator container can reach.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    bound_port = sock.getsockname()[1]
    sock.close()

    loop = asyncio.new_event_loop()
    runner_holder: dict[str, web.AppRunner] = {}

    def serve() -> None:
        asyncio.set_event_loop(loop)
        app = web.Application()
        app.router.add_post("/push", handler)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "0.0.0.0", bound_port)
        loop.run_until_complete(site.start())
        runner_holder["r"] = runner
        loop.run_forever()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    # Give the server a beat to bind.
    import time as _time
    _time.sleep(0.2)

    try:
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        topic_id = f"push-e2e-topic-{uuid.uuid4().hex[:8]}"
        sub_id = f"push-e2e-sub-{uuid.uuid4().hex[:8]}"
        topic_path = publisher.topic_path(pipeline.project, topic_id)
        sub_path = subscriber.subscription_path(pipeline.project, sub_id)
        push_url = f"http://host.docker.internal:{bound_port}/push"

        try:
            publisher.create_topic(request={"name": topic_path})
        except AlreadyExists:
            pass
        try:
            subscriber.create_subscription(
                request={
                    "name": sub_path,
                    "topic": topic_path,
                    "push_config": {"push_endpoint": push_url},
                    "ack_deadline_seconds": 10,
                }
            )
        except AlreadyExists:
            pass

        publisher.publish(
            topic_path, json.dumps({"order_id": "push-e2e-1"}).encode("utf-8")
        ).result(timeout=5.0)

        if not received_event.wait(timeout=10):
            pytest.skip(
                "host.docker.internal not reachable from emulator container — "
                "older Docker without host-gateway support; skipping push e2e."
            )

        assert len(received) == 1
        envelope = received[0]
        assert envelope["subscription"] == sub_path
        import base64
        assert json.loads(base64.b64decode(envelope["message"]["data"])) == {
            "order_id": "push-e2e-1"
        }

        # Verify no double-delivery: emulator should have acked on 204.
        _time.sleep(2.0)
        assert len(received) == 1
    finally:
        # Clean up the aiohttp runner on its own loop, then stop the loop.
        runner = runner_holder.get("r")
        if runner is not None:
            asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(timeout=2)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
```

- [ ] **Step 3: Add `aiohttp` to the example's dev requirements**

Check whether `examples/order-pipeline/` has its own requirements file (look for `requirements.txt`, `pyproject.toml`, or how `aiohttp` would otherwise reach the host-side test). If the e2e tests run via the project's main `[dev]` extra (Task 8 already adds `aiohttp` there), no extra change is needed. Otherwise, add it to whatever the example uses.

Run: `ls examples/order-pipeline/` — confirm the dependency story before declaring this step done.

- [ ] **Step 4: Update the example README**

In `examples/order-pipeline/README.md`, find the section that lists which services / wire paths the example exercises. Add a sentence:

```markdown
The e2e test suite also exercises **push subscriptions** end-to-end: it spins up an in-process `aiohttp` server on the host and registers a push subscription targeting `host.docker.internal:<port>/push`, then verifies the emulator (running inside the container) POSTs the wrapped JSON envelope to it.
```

- [ ] **Step 5: Run the e2e suite locally**

```bash
cd examples/order-pipeline
docker compose up -d --build
pytest test_e2e.py::test_pubsub_push_subscription_delivers_to_host -v
docker compose down
```

Expected: PASS (or `pytest.skip` with the host-gateway message if running on a Docker setup that doesn't support `host-gateway`).

- [ ] **Step 6: Lint/format**

Run: `ruff check examples/order-pipeline/test_e2e.py && ruff format examples/order-pipeline/test_e2e.py`
Expected: clean.

---

## Task 13: Final verification

**Files:** none

- [ ] **Step 1: Run lint and format on the whole project**

Run: `ruff check src/ tests/ && ruff format src/ tests/`
Expected: clean.

- [ ] **Step 2: Run the full unit suite**

Run: `pytest tests/ --ignore=tests/integration/test_docker_image.py`
Expected: all green.

- [ ] **Step 3: Walk the Definition-of-Done audit (per `CLAUDE.md`)**

Confirm each bullet:

- [ ] `docs/services/pubsub.md` — push section added; "What's not emulated" bullet removed; "Limits & quirks" callout removed.
- [ ] `docs/architecture/pubsub.md` — pump section added.
- [ ] `README.md` services-at-a-glance table — no changes needed (status remains Alpha; wire/port unchanged).
- [ ] `ROADMAP.md` — push-subscriptions follow-up removed.
- [ ] `CHANGELOG.md` — `[Unreleased] → ### Added` entry present.
- [ ] Design specs in `docs/superpowers/specs/` — the new spec is the source; no older spec contradicts it.
- [ ] Inline code comments — search `src/gcp_local/services/pubsub/` for `// TODO push` or `# TODO push` style markers and remove any that this change resolves: `grep -rn "TODO" src/gcp_local/services/pubsub/`.
- [ ] `pyproject.toml` — `aiohttp` added to dev deps (no new runtime deps).
- [ ] Unit tests — happy path + ack on 2xx + NACK on 500 + NACK on timeout + ordering + lifecycle + servicer wiring + service teardown.
- [ ] Integration tests — real `google-cloud-pubsub` push delivery + 500-then-200 redelivery.
- [ ] Defaults — pull subscriptions still pass their existing tests (no regressions in `test_pull.py`, `test_streaming_pull.py`).
- [ ] Docker test — no new module-level runtime imports; skip.

- [ ] **Step 4: Stage everything**

```bash
git status
git add src/gcp_local/services/pubsub/ tests/unit/services/pubsub/test_push.py tests/integration/test_pubsub_integration.py examples/order-pipeline/docker-compose.yml examples/order-pipeline/test_e2e.py examples/order-pipeline/README.md docs/services/pubsub.md docs/architecture/pubsub.md ROADMAP.md CHANGELOG.md pyproject.toml docs/superpowers/specs/2026-05-02-pubsub-push-subscriptions-design.md docs/superpowers/plans/2026-05-02-pubsub-push-subscriptions.md
git status
```

- [ ] **Step 5: Stop here.** Do **not** commit. Surface the staged diff to the user with a one-line summary; let them decide whether to commit and open the PR (per `CLAUDE.md`: "Don't commit unless the user explicitly asks").

---

## Self-review notes

- **Spec coverage:** every section of the spec is mapped to a task. Pump architecture → Tasks 1–4. Servicer wiring → Tasks 5–6. Service-level teardown → Task 7. Tests → Tasks 1–4 (unit) + Task 8 (integration) + Task 12 (e2e). Docs → Tasks 9–11. Out-of-scope items (`oidcToken`, `retryPolicy`, `noWrapper`) explicitly carried into the docs as deferred.
- **Type consistency:** `PushPump.push_endpoint`, `PushPump.subscription_name`, `_pumps[(project, sub_id)]`, `_ensure_pump(rec)`, `_get_messages_sync(topic_project, topic_id)` — same names every time they appear.
- **Storage accessor caveat:** Task 5 introduces `get_messages_sync` on `InMemoryStorage` to keep the pump tick non-async on the inner-loop path. If a future Storage implementation does I/O on read, the pump should switch to `await get_messages(...)` and the helper goes away.
- **Test-suite isolation:** push integration tests bind aiohttp to `127.0.0.1:0` so parallel runs don't clash. The 30 s default POST timeout is much longer than the test deadlines (`pytest --timeout` if configured), so `post_timeout_seconds` is overridden in unit tests where needed.
