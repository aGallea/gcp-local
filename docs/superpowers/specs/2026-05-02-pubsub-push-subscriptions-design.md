# Pub/Sub push subscriptions — design

**Status:** approved (auto-mode brainstorm, 2026-05-02)
**Closes roadmap follow-up:** "Push subscriptions — `pushConfig` is accepted and stored, but the emulator does not POST to the URL." (`ROADMAP.md`)

## Context

The Pub/Sub service ships with `Subscription.pushConfig` accept-and-stored. `docs/services/pubsub.md` § "What's not emulated" calls it explicitly inert — `pushConfig` is returned by `GetSubscription` but the emulator never POSTs anywhere. Pull and StreamingPull are fully implemented through a per-subscription `SubscriptionBacklog` (`src/gcp_local/services/pubsub/engine/backlog.py`) with ack-leases, NACK queue, ordering-key blocking, and a 1 s `RedeliverySweeper`.

This spec implements push delivery on top of that existing machinery — no new state machine, no new redelivery story. A push subscription is a pull subscription with a background pump that calls `pull` → POST → `acknowledge` / NACK.

## Goal

When `Publish` lands on a topic that has a subscription with `push_config.push_endpoint` set, the emulator POSTs each message to that endpoint with a body matching real Pub/Sub's wrapped JSON envelope. A `2xx` response acks the message; anything else (non-2xx, connection error, timeout) NACKs it and the redelivery sweeper redrives.

## Non-goals (deferred)

- **`oidcToken` JWT signing** — `pushConfig.oidcToken` stays stored but never produces an `Authorization` header. Documented as a known gap.
- **`retryPolicy.minimumBackoff` / `maximumBackoff`** — still stored-not-evaluated. NACK redrives at the next pump tick (matches pull). Closing this gap is a separate follow-up that should apply uniformly to pull and push.
- **`pushConfig.attributes`** — accepted and stored on the resource; not echoed back as HTTP headers (real Pub/Sub uses these for `x-goog-version` etc.).
- **`noWrapper` mode** — always send the wrapped envelope.
- **Fanout / batched POSTs** — the pump is strictly serial per subscription (one in-flight message at a time). Real Pub/Sub may parallelize; we don't.

## Architecture

### `PushPump` — new class in `src/gcp_local/services/pubsub/engine/push.py`

```python
class PushPump:
    def __init__(
        self,
        *,
        subscription_name: str,            # "projects/<p>/subscriptions/<s>"
        push_endpoint: str,
        backlog: SubscriptionBacklog,
        get_messages: Callable[[], list[MessageRecord]],
        post_timeout_seconds: float = 30.0,
        idle_wait_seconds: float = 10.0,
    ) -> None: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

`get_messages` is a callable returning the topic's current message list (the same way the servicer feeds `backlog.pull` today). The pump owns its own `httpx.AsyncClient` and a stop `asyncio.Event`.

### Pump loop

```python
async def _run(self) -> None:
    while not self._stop.is_set():
        delivered = await self._backlog.pull(
            messages=self._get_messages(),
            max_count=1,
            now=dt.datetime.now(dt.UTC),
        )
        if not delivered:
            try:
                await asyncio.wait_for(
                    self._backlog.deliverable.wait(),
                    timeout=self._idle_wait_seconds,
                )
            except TimeoutError:
                pass
            self._backlog.deliverable.clear()
            continue

        d = delivered[0]
        ok = await self._post(d.message)
        if ok:
            await self._backlog.acknowledge([d.ack_id])
        else:
            await self._backlog.modify_ack_deadline([(d.ack_id, 0)])  # NACK
```

Why `max_count=1`:
- One in-flight POST per subscription keeps ordering trivially correct (the backlog already serializes ordered keys, but for non-ordered keys we still want sequential delivery so a slow handler doesn't reorder visibly).
- Real Pub/Sub fanout would require per-message ack tracking which the backlog already provides — but unary delivery is the simplest correct shape.

### POST envelope

```json
{
  "message": {
    "data": "<base64-of-MessageRecord.data>",
    "attributes": { ... },
    "messageId": "<MessageRecord.message_id>",
    "publishTime": "<RFC3339, e.g. 2026-05-02T12:34:56.789012Z>",
    "orderingKey": "<MessageRecord.ordering_key, may be empty>"
  },
  "subscription": "projects/<p>/subscriptions/<s>"
}
```

Headers:
- `Content-Type: application/json`
- `User-Agent: gcp-local-pubsub-push/<package-version>`

Omit fields when empty? Real Pub/Sub omits `attributes` when none and omits `orderingKey` when empty. We'll match that to avoid surprising user-side parsers that distinguish missing-vs-empty.

### Servicer wiring

`SubscriberServicer` gains:

```python
self._pumps: dict[tuple[str, str], PushPump] = {}
```

At the end of `CreateSubscription` (after the `SubscriptionRecord` is in storage and the backlog is created), if `push_config.push_endpoint` is non-empty, instantiate and start a `PushPump`.

`UpdateSubscription` may toggle push↔pull or change the endpoint:
- If the new record has no push endpoint and an old pump exists → stop the old pump.
- If the new record has a push endpoint that differs from the old one → stop old, start new.
- If the new record has the same endpoint as the old → no-op.

`DeleteSubscription` stops the pump if any.

### Lifecycle integration with `PubSubService`

`PubSubService.stop()` already stops the redelivery sweeper. It now also cancels every pump in `subscriber._pumps` via `asyncio.gather(*(p.stop() for p in pumps), return_exceptions=True)` before `server.stop(grace=0)`.

`reset_state()` cancels pumps too (and clears the dict), since storage is being wiped.

## Failure modes

| Symptom | Pump response |
|---|---|
| Endpoint returns 2xx | `acknowledge` |
| Endpoint returns non-2xx | NACK (`modify_ack_deadline(..., 0)`) |
| `httpx.ConnectError` / DNS failure | NACK |
| `httpx.ReadTimeout` past `post_timeout_seconds` | NACK |
| Pump task crashes mid-POST (unexpected exception) | Pump logs `exception(...)`, continues loop. Lease deadline expires → sweeper redrives. |
| Process exits between POST and ack | Lease deadline expires → next process boot sees no lease (storage in-memory) but the message is gone too; same trade-off as pull. |

## Test plan

### Unit (`tests/unit/services/pubsub/test_push.py`)

- **Payload shape** — POST received by a fake `httpx.MockTransport` carries the wrapped envelope, base64-encoded data, RFC3339 publish time, correct `subscription` path.
- **Ack on 2xx** — fake transport returns 200; backlog's lease list is empty afterwards.
- **NACK on non-2xx** — fake transport returns 500; lease is dropped from `_leases`, `_nacked` contains the message index, redelivery sweeper / next pump tick redrives.
- **NACK on timeout** — fake transport raises `httpx.ReadTimeout`; same as above.
- **Ordering key serialization** — two messages with the same ordering key, second POST blocked until first is ack'd. Verify second POST happens after the first response.
- **Lifecycle: create-then-delete** — pump task is cancelled and awaited; no orphan tasks at end of test.
- **Lifecycle: update endpoint** — old pump cancelled, new pump POSTs to the new URL.
- **Empty attributes / empty orderingKey omitted from envelope** — assert keys absent (not `null`, not `""`).

### Integration (`tests/integration/test_pubsub_integration.py`)

- **Real `google-cloud-pubsub` push delivery** — start a tiny aiohttp server on a random port, create a push subscription pointing at it via the real client, publish a message, assert the server received the wrapped envelope and the emulator considered it acked (no redelivery on the next sweep).
- **Real client NACK redelivery** — server returns 500 once, then 200; assert the second POST carries the same `messageId`.

### End-to-end (`examples/order-pipeline/test_e2e.py`)

- **Push delivery against the docker-compose'd emulator** — bind aiohttp to a host port, register a push subscription targeting `http://host.docker.internal:<port>/push` (the emulator runs in the container; `host.docker.internal:host-gateway` is added to `docker-compose.yml`), publish via the real client, verify the host receives the wrapped envelope and the emulator considers it acked. Skips with a clear message if `host.docker.internal` does not resolve from inside the container.

### Docker test

No new module-level imports of new third-party packages (`httpx` already declared in `dependencies`). Skip the Docker rebuild step.

## Documentation updates

- `docs/services/pubsub.md`:
  - Remove "Push subscriptions are inert" from "Limits & quirks".
  - Remove the "`Subscription.pushConfig`" bullet from "What's not emulated".
  - Add a "Push subscriptions" section: payload spec (JSON envelope), default timeout, ack/NACK rules via HTTP status, `oidcToken` not emitted, `pushConfig.attributes` not echoed.
- `docs/architecture/pubsub.md`: add the push pump to the per-subscription state diagram and describe its loop alongside the existing pull/streaming-pull description.
- `ROADMAP.md`: remove the "Push subscriptions — `pushConfig` is accepted and stored, but the emulator does not POST to the URL." bullet under "Pub/Sub".
- `CHANGELOG.md`: under `## [Unreleased]` → `### Added`: "**Pub/Sub:** push subscriptions now deliver. When a subscription has `push_config.push_endpoint`, the emulator POSTs each published message to the endpoint as a wrapped JSON envelope; 2xx acks the message, anything else NACKs and the existing ack-deadline redelivery loop redrives. `oidcToken`, `retryPolicy` backoff, `pushConfig.attributes`, and `noWrapper` remain deferred — see `docs/services/pubsub.md`."

## Build sequence (preview — full plan to be written by `writing-plans`)

1. `engine/push.py` + unit tests on the pump in isolation (mocked backlog).
2. Wire pump into `SubscriberServicer.CreateSubscription` / `UpdateSubscription` / `DeleteSubscription`.
3. Wire teardown into `PubSubService.stop` / `reset_state`.
4. Integration test through real `google-cloud-pubsub` + aiohttp server.
5. Docs / ROADMAP / CHANGELOG.

Each step is independently testable; the PR ships as one cohesive unit (under the 400 LOC production-code budget — the pump itself is ~80 LOC, servicer wiring is ~30 LOC, the rest is docs and tests).
