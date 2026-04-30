# Pub/Sub — internals

This document describes how the Pub/Sub emulator is implemented. For the user-facing API surface (what's emulated, how to connect, examples), see [`docs/services/pubsub.md`](../services/pubsub.md). For the cross-cutting framework that this service plugs into, see [`docs/architecture/overview.md`](overview.md).

## At a glance

The Pub/Sub emulator is a pure gRPC service that exposes the Google Cloud Pub/Sub v1 Publisher and Subscriber APIs on port **8085** (the canonical Pub/Sub emulator port that the official `google-cloud-pubsub` client reads from `PUBSUB_EMULATOR_HOST` automatically). Storage is **in-memory only** — even with `PERSIST=1`, no disk-backed backend is wired up. The trade-off is justified by Pub/Sub's inherently transient workload (production retention is a sliding 7-day window) and by the fact that emulator tests almost always start from an empty backlog.

The service reuses the gRPC server framework that Secret Manager introduced (a dedicated `grpc.aio.Server` per service, vendored proto stubs, an `asyncio.Lock`-protected in-memory storage layer). What's new is the **delivery state machine** in `engine/`: per-subscription backlog, ack-lease tracking, ordering-key gating, and the 1-second redelivery sweeper.

## Wire & port

gRPC on port **8085**. The official Python client honors `PUBSUB_EMULATOR_HOST=localhost:8085` natively — it opens an insecure channel and skips authentication when the env var is set. The port is overridable via `PUBSUB_EMULATOR_PORT` through the standard `port_overrides` machinery (`ctx.port_overrides.get("pubsub", 8085)` in `service.py`).

The cross-service admin HTTP API (`/_emulator/health`, `/services`, `/reset`) lives on port **4510**, not on 8085. The service registers as `pubsub` (entry-point in `pyproject.toml`'s `[project.entry-points."gcp_local.services"]` block); it can be selected via `SERVICES=pubsub` (or as part of a comma-separated list).

## Vendored proto stubs

Pre-generated Python stubs are checked into the repository under:

```
src/gcp_local/generated/google/pubsub/v1/
    pubsub_pb2.py / pubsub_pb2_grpc.py / pubsub_pb2.pyi
    schema_pb2.py / schema_pb2_grpc.py / schema_pb2.pyi
```

`schema.proto` is vendored because `pubsub.proto` imports it for the `Topic.schema_settings.encoding` enum — it is a transitive proto dependency, not a deliberate choice to ship the schema service. The servicer registers `PublisherServicer` and `SubscriberServicer`; it deliberately **does not** register `SchemaServiceServicer`, so any client RPC into `SchemaService` falls through to the generated base class and returns gRPC `UNIMPLEMENTED`.

Regeneration is performed by `scripts/gen_pubsub_protos.sh`, which:

1. Runs `grpc_tools.protoc` against the `.proto` sources in `protos/google/pubsub/v1/` with `googleapis-common-protos` on the proto path.
2. Post-processes generated files to rewrite `from google.pubsub.v1 import …` lines to `from gcp_local.generated.google.pubsub.v1 import …` so imports resolve inside the package tree.

`google-cloud-pubsub` is a **test-only** (dev) dependency, used by integration tests. The runtime image does not import it.

## Storage model

`InMemoryStorage` (in `storage.py`) holds:

| Field | Type | Purpose |
|---|---|---|
| `topics` | `dict[(project, topic_id), TopicRecord]` | Topic metadata |
| `topic_messages` | `dict[(project, topic_id), list[MessageRecord]]` | Append-only per-topic message log |
| `subscriptions` | `dict[(project, sub_id), SubscriptionRecord]` | Subscription metadata |
| `sub_cursor` | `dict[(project, sub_id), int]` | Next index into the topic's `topic_messages` list |
| `sub_leases` | `dict[(project, sub_id), dict[ack_id, AckLease]]` | Outstanding (in-flight, unacked) deliveries |
| `sub_nacked` | `dict[(project, sub_id), list[message_index]]` | Explicitly NACKed indices, redeliver-now queue |
| `sub_ordering_blocked` | `dict[(project, sub_id), set[ordering_key]]` | Keys with an unacked or NACKed message in flight |
| `_topic_msg_seq` | `dict[(project, topic_id), int]` | Monotonic counter that mints `<topic_id>-<n>` IDs |

The records (defined in `models.py`):

```python
@dataclass
class TopicRecord:
    project: str
    topic_id: str
    labels: dict[str, str]
    message_storage_policy: dict | None  # accepted, not enforced
    kms_key_name: str | None              # accepted, not enforced
    schema_settings: dict | None          # accepted, not enforced
    create_time: datetime                 # internal; not on the Topic wire shape

@dataclass
class MessageRecord:
    message_id: str           # "<topic_id>-<n>", n monotonic per topic
    publish_time: datetime
    data: bytes
    attributes: dict[str, str]
    ordering_key: str         # "" when unset

@dataclass
class SubscriptionRecord:
    project: str
    subscription_id: str
    topic_project: str
    topic_id: str
    ack_deadline_seconds: int       # default 10
    enable_message_ordering: bool
    push_config: dict | None        # stored, never delivered to
    filter: str                      # stored, never evaluated
    dead_letter_policy: dict | None # accepted, no-op
    retry_policy: dict | None       # accepted, no-op
    labels: dict[str, str]
    enable_exactly_once_delivery: bool   # accepted, downgraded to at-least-once
    create_time: datetime

@dataclass
class AckLease:
    ack_id: str               # opaque token, e.g. "lease-<uuid>"
    message_id: str
    deadline_at: datetime     # absolute; redelivery sweeper compares against now()
```

The `topic_messages` list is **append-only** for the lifetime of the topic. Subscriptions advance their own `sub_cursor` independently, and a message is removed from a subscription's view when it is acked (via lease drop) — but the underlying `MessageRecord` stays in `topic_messages` so other subscriptions can still see it. The list grows unbounded; this is documented as an internals-level limitation below.

### Concurrency

Mutations are serialized through `asyncio.Lock`s:

- A **topic-level lock** gates `Publish` so the message-ID counter advances and the message list grows atomically with the deliverable-event notification.
- A **per-subscription lock** keyed by `(project, sub_id)` gates the `sub_cursor` / `sub_leases` / `sub_nacked` / `sub_ordering_blocked` quartet so a Pull, Acknowledge, ModifyAckDeadline, sweeper tick, and Seek can never interleave inconsistently.

## Request lifecycle: 14 RPCs

The servicer (`servicer.py`) splits into `PublisherServicer` and `SubscriberServicer`. The table below maps each in-scope RPC to the storage / engine helpers it touches:

| RPC | Storage / engine helpers |
|---|---|
| `CreateTopic` | `storage.create_topic` |
| `GetTopic` | `storage.get_topic` |
| `UpdateTopic` | `storage.update_topic` (labels-only patch) |
| `DeleteTopic` | `storage.delete_topic` (cascades through `topic_messages`; subscriptions to a deleted topic surface `NOT_FOUND` on next Pull) |
| `ListTopics` | `storage.list_topics` + shared `_paginate` (page size capped at 1000) |
| `ListTopicSubscriptions` | `storage.list_topic_subscriptions` + shared `_paginate` |
| `Publish` | `storage.append_messages` (under topic lock; mints `<topic_id>-<n>` IDs, stamps `publish_time = now()`); emits StateHub `pubsub.message.published` event; notifies every subscription's deliverable `asyncio.Event` |
| `CreateSubscription` | `storage.create_subscription` (topic resolved before insert; `enable_exactly_once_delivery` logged + downgraded; `filter` / `pushConfig` stored verbatim) |
| `GetSubscription` | `storage.get_subscription` |
| `UpdateSubscription` | `storage.update_subscription` (labels + `ackDeadlineSeconds` only) |
| `DeleteSubscription` | `storage.delete_subscription` (drops cursor, leases, NACK queue, ordering-block set; cancels any sweeper task) |
| `ListSubscriptions` | `storage.list_subscriptions` + `_paginate` |
| `Pull` | `engine/backlog.py::pull` (see below) |
| `StreamingPull` | `engine/streaming.py::streaming_pull_loop` (calls `backlog.pull` repeatedly; processes mid-stream `ack_ids`/`modify_deadline_*` deltas) |
| `Acknowledge` | `engine/backlog.py::acknowledge` |
| `ModifyAckDeadline` | `engine/backlog.py::modify_ack_deadline` (positive seconds → extend lease; zero → NACK) |
| `Seek` | `engine/backlog.py::seek_to_time` (binary search by `publish_time`); `Seek(snapshot=…)` aborts with `UNIMPLEMENTED` |

`engine/backlog.py` owns all delivery-state mutations; the servicer only marshals proto requests into engine calls and engine results back into proto responses. The 1-second redelivery sweeper is owned by `engine/delivery.py`. The streaming-pull session loop (with its per-stream flow-control budget) lives in `engine/streaming.py`.

## Delivery state machine

The whole §5 of the spec lives in `engine/backlog.py` and `engine/delivery.py`. Pseudocode for the four primary operations:

### Pull / StreamingPull

```
async def pull(sub, max_messages, return_immediately):
    async with sub_lock:
        # 1. Opportunistic on-pull lease sweep — keeps a busy puller from
        #    waiting an extra second for the timer-based sweeper.
        for lease in list(sub_leases[sub].values()):
            if lease.deadline_at < now():
                sub_nacked[sub].append(lease.message_index)
                sub_leases[sub].pop(lease.ack_id)
                sub_ordering_blocked[sub].discard(lease.ordering_key)

        # 2. Build the candidate list — NACKed first, then advance the cursor.
        candidates = list(sub_nacked[sub])
        sub_nacked[sub].clear()
        i = sub_cursor[sub]
        while len(candidates) < max_messages and i < len(topic_messages[topic]):
            msg = topic_messages[topic][i]
            if sub.enable_message_ordering and msg.ordering_key in sub_ordering_blocked[sub]:
                i += 1
                continue
            candidates.append(i)
            i += 1
        sub_cursor[sub] = i

        # 3. Mint a lease for each candidate; record the ordering-key block.
        for idx in candidates[:max_messages]:
            ack_id = "lease-" + uuid()
            sub_leases[sub][ack_id] = AckLease(
                ack_id, topic_messages[topic][idx].message_id,
                deadline_at=now() + sub.ack_deadline_seconds,
            )
            if sub.enable_message_ordering and msg.ordering_key:
                sub_ordering_blocked[sub].add(msg.ordering_key)

    return [(ack_id, msg) for ack_id, msg in built]
```

If `candidates` is empty after step 2 and `return_immediately` is `false`/unset, the call awaits the subscription's deliverable `asyncio.Event` (set whenever a `Publish` lands on the relevant topic, or a NACK / sweeper redelivery makes a message redeliverable) for up to 90 seconds before returning empty. `return_immediately=true` returns whatever's available — possibly zero messages.

### Acknowledge / ModifyAckDeadline

```
async def acknowledge(sub, ack_ids):
    async with sub_lock:
        for aid in ack_ids:
            lease = sub_leases[sub].pop(aid, None)
            if lease and lease.ordering_key:
                sub_ordering_blocked[sub].discard(lease.ordering_key)
                # Wake any pull blocked on a same-key gate.
                deliverable_event[sub].set()

async def modify_ack_deadline(sub, ack_ids, seconds):
    async with sub_lock:
        if seconds == 0:        # NACK
            for aid in ack_ids:
                lease = sub_leases[sub].pop(aid, None)
                if lease:
                    sub_nacked[sub].append(lease.message_index)
                    sub_ordering_blocked[sub].discard(lease.ordering_key)
            deliverable_event[sub].set()
        else:                   # Extend
            for aid in ack_ids:
                if aid in sub_leases[sub]:
                    sub_leases[sub][aid].deadline_at = now() + seconds
```

### Redelivery sweeper

`engine/delivery.py` runs one `asyncio.Task` per subscription:

```
async def sweeper_loop(sub):
    while not cancelled:
        async with sub_lock:
            for lease in list(sub_leases[sub].values()):
                if lease.deadline_at < now():
                    sub_leases[sub].pop(lease.ack_id)
                    sub_nacked[sub].append(lease.message_index)
                    sub_ordering_blocked[sub].discard(lease.ordering_key)
            if any_swept:
                deliverable_event[sub].set()
        await asyncio.sleep(1.0)
```

The sweeper is started lazily on the first lease and idles cheaply (one second-granularity tick) when `sub_leases[sub]` is empty. It is canceled on `DeleteSubscription`.

### Ordering-key gating

A message with key `K` on an ordered subscription is only minted a lease if `K` is **not** currently in `sub_ordering_blocked[sub]`. When a message with key `K` is acked, `K` is removed from the set (unblocking later messages); when it is NACKed or expires, it is re-queued at the head of the redelivery list and `K` stays blocked until the redelivery is acked. Messages with empty `ordering_key` are never blocked. Subscriptions without `enable_message_ordering=True` ignore the key entirely — same-key messages are delivered concurrently and out-of-order is possible.

### Seek by time

```
async def seek_to_time(sub, t):
    async with sub_lock:
        msgs = topic_messages[(sub.topic_project, sub.topic_id)]
        i = bisect_left(msgs, t, key=lambda m: m.publish_time)
        sub_cursor[sub] = i
        sub_leases[sub].clear()         # in-flight leases are abandoned, not re-NACKed
        sub_nacked[sub].clear()
        sub_ordering_blocked[sub].clear()
        deliverable_event[sub].set()
```

`Seek(snapshot=…)` returns gRPC `UNIMPLEMENTED` — snapshots are post-v1.

## StreamingPull session loop

`engine/streaming.py::streaming_pull_loop` runs as an async generator over the subscription's deliverable Event. Layout:

1. The first request from the client carries `subscription`, initial `stream_ack_deadline_seconds`, and flow-control caps (`max_outstanding_messages`, `max_outstanding_bytes`). The session reads these once.
2. A fan-in task (`asyncio.create_task(_consume_client_messages(...))`) drains subsequent client requests, each of which may contain `ack_ids` (treated as Acknowledge), `modify_deadline_ack_ids` + `modify_deadline_seconds` (ModifyAckDeadline, including NACK when seconds==0), and a `stream_ack_deadline_seconds` override.
3. The main loop computes remaining flow credit (`(max_outstanding_messages - in_flight, max_outstanding_bytes - in_flight_bytes)`), calls `backlog.pull` for up to that many messages with a long-poll budget, and yields a `StreamingPullResponse` whenever messages come back.
4. Yielded counts are deducted from the flow-control budget; ack/nack from step 2 returns the budget. The loop stops yielding when either counter reaches zero and resumes when the client acks/nacks.
5. Termination: when `context.is_active()` returns false (client cancel or stream close), the fan-in task is canceled and the leases held by this stream are left in place — they expire normally via the sweeper (or the client may have acked them already). There is no special "stream close → NACK all" behavior.

Per-stream limits are read from the initial `StreamingPullRequest` and never re-read; this matches the official client, which only sets them on stream open.

## Cross-service integration

`Publish` emits a `pubsub.message.published` event on the StateHub bus:

```python
{
  "topic": "projects/<project>/topics/<topic_id>",
  "message_id": "<topic_id>-<n>",
  "attributes": {...},
  "size_bytes": len(data),
  "publish_time": "2026-04-29T...",
}
```

This is the local-only hook that test code uses to assert "the publisher actually published" without polling Pub/Sub. The future push-delivery work (post-v1) will subscribe to this same event internally rather than re-running publish-side logic.

There is no Pub/Sub-to-GCS or Pub/Sub-to-BigQuery wiring in v1 — the StateHub plumbing is in place, but the actual subscription types are deferred.

## Errors

Internal exceptions in `errors.py` map to gRPC status codes via the helper that Secret Manager already established:

| Internal exception | gRPC code | When |
|---|---|---|
| `TopicNotFound` / `SubscriptionNotFound` | `NOT_FOUND` | resource missing |
| `TopicAlreadyExists` / `SubscriptionAlreadyExists` | `ALREADY_EXISTS` | duplicate create |
| `InvalidName` | `INVALID_ARGUMENT` | name fails the Pub/Sub regex (3–255 chars, `[A-Za-z][A-Za-z0-9-_.~+%]*`, no `goog` prefix) |
| `InvalidArgument` | `INVALID_ARGUMENT` | bad ack_id format, missing required field, etc. |
| `Unimplemented` | `UNIMPLEMENTED` | IAM, snapshot RPCs, snapshot Seek, schema RPCs |
| Uncaught | `INTERNAL` | fallback |

Statuses are produced via `await context.abort(grpc.StatusCode.X, message)` inside the async servicer methods. Naming validation lives in `names.py` and matches the real Pub/Sub regex; tests in `test_names.py` assert that gcloud-style names round-trip and that obvious garbage (empty, `goog`-prefixed, illegal characters) is rejected with `INVALID_ARGUMENT`.

## Tests

**Unit tests** live under `tests/unit/services/pubsub/` — one file per concern:

| File | What it covers |
|---|---|
| `test_names.py` | Name parser/validator + edge cases (gcloud-style names, `goog` prefix, illegal chars). |
| `test_models.py` | Record dataclass behavior + serializers. |
| `test_storage.py` | `InMemoryStorage` CRUD; lease lifecycle; cursor and NACK-queue interactions. |
| `test_servicer_topics.py` | Publisher RPCs (`CreateTopic` / `GetTopic` / `UpdateTopic` / `DeleteTopic` / `ListTopics` / `ListTopicSubscriptions`) against an in-process gRPC channel. |
| `test_servicer_subscriptions.py` | Subscriber CRUD RPCs; accept-and-store for `pushConfig` / `filter` / `deadLetterPolicy`. |
| `test_publish.py` | `Publish` allocates `<topic_id>-<n>` IDs monotonically; populates `publishTime`; emits StateHub event. |
| `test_pull.py` | Unary `Pull` with empty / non-empty backlog; `returnImmediately`; `maxMessages`. |
| `test_ack_modack.py` | Ack drops the lease and unblocks the ordering key; ModAck extends; ModAck=0 NACKs and triggers redelivery. |
| `test_redelivery.py` | Expired leases redeliver after the 1-second sweep tick (the sweeper is patched to a faster cadence in tests). |
| `test_ordering.py` | Same-key messages serialize across NACK → redelivery; empty key never blocks; subscriptions without ordering ignore the key. |
| `test_streaming_pull.py` | Bidirectional stream delivers; honors flow control caps; processes mid-stream ack/modack deltas; client-cancel cleans up. |
| `test_seek.py` | Seek-to-time rewinds the cursor, drops in-flight leases, clears NACK queue, clears ordering blocks. |
| `test_errors.py` | Error-envelope shapes for each `(internal exception → grpc code)` row. |
| `test_backlog.py` | Engine-level coverage of the per-subscription state machine in isolation. |
| `test_service_scaffold.py` | `Service` protocol wiring (`start` / `stop` / `health` / `reset`); port resolution; persist-flag log line. |

**Integration tests** in `tests/integration/test_pubsub_integration.py` start the emulator in-process and drive it with the real `google-cloud-pubsub` Python client over a live gRPC channel. The five cases cover:

1. Full publisher + subscriber lifecycle (create topic + subscription, publish 100 messages, pull-and-ack all).
2. StreamingPull via `subscriber.subscribe(callback)` with a real `Future` returned by the client.
3. Ordering keys via `PublisherOptions(enable_message_ordering=True)`.
4. Seek-to-time round-trip.
5. Resource-not-found and duplicate-create error mapping.

The existing `emulator` fixture in `tests/integration/conftest.py` is extended to include `pubsub` in the default service list.

## Internals-level limitations

These are the gaps a consumer should know about. User-visible "what's not emulated" lives in [`docs/services/pubsub.md`](../services/pubsub.md); this list is internals-flavored.

- **In-memory only**, even with `PERSIST=1`. Topics, subscriptions, message backlogs, and subscription cursors are lost across restarts. The service logs an info-level line at startup so the user knows. Disk persistence is mechanical to add later if a workflow needs it.
- **Topic backlog grows unbounded** for the process lifetime. Real Pub/Sub retains messages for up to 7 days; the emulator retains until the process exits or every subscription has acked them. Reset between tests, or restart the container.
- **Filters are not evaluated.** Every published message is delivered to every matching subscription regardless of `Subscription.filter`. The string round-trips on `GetSubscription` but has no effect.
- **Push subscriptions are no-ops.** `pushConfig` is stored and reflected on `GetSubscription`, but the emulator never POSTs to the URL. Push delivery requires an outbound HTTP loop with retry/backoff, deferred to post-v1.
- **Exactly-once delivery is downgraded to at-least-once.** `enableExactlyOnceDelivery=true` is accepted on the wire, logged, and otherwise ignored. There is no client-side dedup, no message-id-based suppression on redelivery, and `ModifyAckDeadlineConfirmation` is not emitted.
- **Single-process delivery.** The whole emulator runs in one Python process; horizontal scale-out is not relevant. All locks are `asyncio.Lock`s, not OS-level mutexes — no leader election, no shared state across replicas.
- **`messageId` shape is `<topic_id>-<n>`** (monotonic per topic), not the opaque 16+ digit IDs the real service mints. Callers that assert on the exact ID shape will need to relax that assertion.
- **`returnImmediately` long-poll cap is 90 seconds.** Real Pub/Sub's deprecated long-poll has a different cap; emulator workflows should not depend on the exact value.
- **No streaming subscriber timeout for slow consumers.** A StreamingPull session that never acks will hold its leases until they expire and the sweeper redelivers; the server does not close the stream on a stuck consumer.
