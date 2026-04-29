# gcp-local — Pub/Sub Service Design

**Date:** 2026-04-29
**Status:** Draft for review
**Scope:** Fourth v1 service — Cloud Pub/Sub. Second gRPC service in the project.
**Core design:** [2026-04-24-gcp-local-core-design.md](./2026-04-24-gcp-local-core-design.md)
**Related:** [2026-04-24-gcp-local-secret-manager-design.md](./2026-04-24-gcp-local-secret-manager-design.md) — gRPC service template.

## 1. Overview

This document specifies the **Pub/Sub emulator** — the fourth real service in `gcp-local` and the second gRPC service after Secret Manager. Success criterion: the official `google-cloud-pubsub` Python client library works unchanged against the emulator for the Publisher + Subscriber APIs across topic CRUD, subscription CRUD, publish, unary `Pull`, `StreamingPull`, `Acknowledge`, `ModifyAckDeadline`, and `Seek` (to time).

Pub/Sub is the most-requested service from local-dev workflows after BigQuery + GCS. The bar is "an event-driven app's `publisher.publish()` and `subscriber.subscribe()` calls round-trip through gcp-local without code changes." Push subscriptions, schemas, snapshots, and BigQuery/GCS subscriptions are explicitly post-v1 (§2.3).

The gRPC framework already exists from Secret Manager; this service reuses it directly.

## 2. Scope (v1)

### 2.1 In scope

**Publisher (`google.pubsub.v1.Publisher`):**

- `CreateTopic`, `GetTopic`, `UpdateTopic` (labels only), `DeleteTopic`
- `ListTopics`, `ListTopicSubscriptions` (with paging)
- `Publish` — single-RPC batch of messages; returns `messageIds`. Server stamps `messageId` (monotonic per topic) and `publishTime`.

**Subscriber (`google.pubsub.v1.Subscriber`):**

- `CreateSubscription`, `GetSubscription`, `UpdateSubscription` (labels + `ackDeadlineSeconds` only), `DeleteSubscription`
- `ListSubscriptions` (with paging)
- `Pull` — unary blocking pull, honors `maxMessages` and `returnImmediately` deprecation (server treats `returnImmediately=true` as a 0-second wait, `false`/unset as a short long-poll up to 90s)
- `StreamingPull` — bidirectional stream, honors per-stream flow control (`stream_ack_deadline_seconds`, `max_outstanding_messages`, `max_outstanding_bytes`)
- `Acknowledge`, `ModifyAckDeadline` — per ackId
- `Seek` — by `time` only (snapshot seek is out-of-v1)

**Delivery semantics:**

- **At-least-once delivery** with ack-deadline-based redelivery. Unacked messages whose deadline has passed are returned to the deliverable pool.
- **Message ordering** by `orderingKey` per subscription: when a subscription has `enableMessageOrdering=true`, messages with the same key are delivered in publish order, and a NACK on an ordered message blocks all later messages with the same key until the NACKed one is redelivered + acked.
- **Per-subscription redelivery sweeper** runs every 1 second and reclaims expired ackIds.
- **Subscription cursor** is the in-memory backlog; messages are append-only inside a topic and reference-counted across subscriptions (§5).

**Project namespacing:**

- `projects/<project>/topics/<name>` and `projects/<project>/subscriptions/<name>` are the primary keys; different projects can hold same names independently.

**In-memory storage only.** Pub/Sub state is intentionally not persisted across restarts even with `PERSIST=1` — production messages are inherently transient and tests almost always start from an empty backlog. Justified explicitly in §6.

**gRPC error shapes** matching real Pub/Sub responses (`NOT_FOUND` on missing resources, `ALREADY_EXISTS` on duplicates, `INVALID_ARGUMENT` on schema/name violations).

**StateHub events** for cross-service integration: `pubsub.message.published` published when a message lands on a topic. (Push delivery to a webhook is post-v1; the StateHub fan-out is the local hook for tests.)

### 2.2 Accepted-and-ignored

These fields are accepted on the wire (so clients don't crash on validation) and stored on the resource, but the emulator does not act on them:

- **Subscription.filter** — stored, never evaluated. Every message is delivered regardless of filter.
- **Subscription.deadLetterPolicy** — stored, never triggered.
- **Subscription.retryPolicy** — stored; the emulator uses a fixed 1-second redelivery sweep regardless.
- **Subscription.expirationPolicy** — stored; subscriptions are never auto-deleted.
- **Subscription.messageRetentionDuration** — stored; the emulator retains messages until ack or process exit.
- **Topic.messageStoragePolicy**, **Topic.kmsKeyName**, **Topic.schemaSettings** — stored, no enforcement.
- **Subscription.pushConfig** — accepted on `CreateSubscription`/`UpdateSubscription` and stored, but no HTTP delivery loop runs. Documented in user docs as a no-op until push is shipped.

**IAM (`GetIamPolicy` / `SetIamPolicy` / `TestIamPermissions`)** — return `UNIMPLEMENTED`, mirroring Secret Manager's current behavior.

### 2.3 Out of v1 (deferred, tracked in `ROADMAP.md`)

- **Push subscriptions actually delivering** — needs an outbound HTTP loop, retry/backoff, and a way to register webhook targets. Substantial enough to be its own follow-up.
- **Subscription filters actually evaluated** against attributes (a small expression-language parser).
- **Schema service** (`SchemaService` RPCs, schema-validated publish).
- **Snapshots** (`CreateSnapshot`, `ListSnapshots`, `GetSnapshot`, `DeleteSnapshot`, `Seek` by snapshot).
- **BigQuery subscriptions, Cloud Storage subscriptions, detached subscriptions.**
- **Exactly-once delivery** (`enableExactlyOnceDelivery=true`) — accepted but downgraded to at-least-once with a warning logged at create time.
- **Persistence** across restarts (current design is in-memory only, see §6).

## 3. Service architecture

### 3.1 Package layout

```
src/gcp_local/services/pubsub/
  __init__.py                  # exports PubSubService
  service.py                   # PubSubService (Service protocol)
  servicer.py                  # PublisherServicer + SubscriberServicer (gRPC handlers)
  engine/
    __init__.py
    backlog.py                 # Backlog: per-subscription deliverable queue + ack tracking
    delivery.py                # ack-deadline sweep loop, ordering-key gating
    streaming.py               # StreamingPull session loop + flow control
  models.py                    # TopicRecord, SubscriptionRecord, MessageRecord, AckLease
  storage.py                   # Storage protocol + InMemoryStorage
  names.py                     # parsers for projects/<p>/topics/<t> and .../subscriptions/<s>
  errors.py                    # exception types + grpc_error mappings
```

Mirrors the Secret Manager layout, with one new subpackage `engine/` for the delivery state machine (analogous to `bigquery/engine/` housing the SQL-execution code).

### 3.2 Port

Default **8085** (canonical Pub/Sub emulator port; clients read `PUBSUB_EMULATOR_HOST` automatically). Override via `PUBSUB_EMULATOR_PORT` through the existing `port_overrides` machinery.

### 3.3 Connection from client code

The official client reads `PUBSUB_EMULATOR_HOST` natively — no code changes needed:

```bash
export PUBSUB_EMULATOR_HOST=localhost:8085
```

```python
from google.cloud import pubsub_v1
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path("my-project", "my-topic")
publisher.create_topic(request={"name": topic_path})
publisher.publish(topic_path, b"hello world").result()
```

### 3.4 gRPC stubs

Same approach as Secret Manager: import the pre-generated servicer bases from the installed `google-cloud-pubsub` package rather than vendoring `.proto` files. We want the pb2_grpc servicer base classes, not the client-side transports. The exact module path is finalized during implementation by `grep -r 'class PublisherServicer' .venv/lib/.../google/` against the installed package; the shape will be:

```python
from google.cloud.pubsub_v1.proto import pubsub_pb2_grpc  # actual path TBV
class PublisherServicer(pubsub_pb2_grpc.PublisherServicer): ...
class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer): ...
```

`google-cloud-pubsub` becomes a **runtime dependency** for this reason (same trade-off as `google-cloud-secret-manager`).

## 4. Data model

### 4.1 Records

```python
@dataclass
class TopicRecord:
    project: str
    topic_id: str  # short name, not the full path
    labels: dict[str, str]
    message_storage_policy: dict | None  # accepted, not enforced
    kms_key_name: str | None              # accepted, not enforced
    schema_settings: dict | None          # accepted, not enforced
    create_time: datetime  # internal only; not on wire (Topic proto has no create_time)

@dataclass
class MessageRecord:
    message_id: str            # monotonic per-topic, e.g. "topic-12"
    publish_time: datetime
    data: bytes
    attributes: dict[str, str]
    ordering_key: str          # "" if unset

@dataclass
class SubscriptionRecord:
    project: str
    subscription_id: str
    topic_project: str
    topic_id: str
    ack_deadline_seconds: int           # default 10
    enable_message_ordering: bool
    push_config: dict | None            # stored, never delivered to
    filter: str                          # stored, never evaluated
    dead_letter_policy: dict | None     # accepted, no-op
    retry_policy: dict | None           # accepted, no-op
    labels: dict[str, str]
    enable_exactly_once_delivery: bool  # accepted, treated as at-least-once
    create_time: datetime

@dataclass
class AckLease:
    """An in-flight delivery — message returned to a subscriber but not yet acked."""
    ack_id: str  # opaque token, e.g. "lease-<uuid>"
    message_id: str
    deadline_at: datetime  # absolute; redelivery sweeper compares against now()
```

### 4.2 Storage shape

`InMemoryStorage` holds:

```python
topics: dict[(project, topic_id), TopicRecord]
topic_messages: dict[(project, topic_id), list[MessageRecord]]   # append-only
subscriptions: dict[(project, sub_id), SubscriptionRecord]

# Per-subscription delivery state:
sub_cursor: dict[(project, sub_id), int]                          # next index into topic_messages
sub_leases: dict[(project, sub_id), dict[ack_id, AckLease]]       # outstanding leases
sub_nacked: dict[(project, sub_id), list[message_index]]          # explicitly NACKed, redeliver-now
sub_ordering_blocked: dict[(project, sub_id), set[ordering_key]]  # keys with an unacked message in flight
```

Topic message lists grow unbounded for the process lifetime — acceptable for an in-memory dev emulator (real Pub/Sub retains 7 days). Documented as an internals-level limitation.

### 4.3 Concurrency

The service uses `asyncio.Lock` per `(project, sub_id)` to serialize backlog mutations. Topic-level locks gate `Publish` so the message list and `sub_cursor` advance consistently.

## 5. Delivery semantics

### 5.1 Pull / StreamingPull

When a subscriber pulls:

1. Acquire the subscription lock.
2. Opportunistic lease sweep: for each `AckLease` with `deadline_at < now()`, push its message index to `sub_nacked` and clear any ordering-key block. The §5.3 timer-based sweeper is the backstop; this on-pull pass keeps a busy puller from waiting an extra second.
3. Build a candidate list:
   - Start with NACKed indices (highest priority — explicit redelivery requests).
   - Then advance the cursor through `topic_messages[topic]`. **For subscriptions with `enableMessageOrdering=true` only:** skip messages whose `ordering_key` is in `sub_ordering_blocked`. Subscriptions without ordering ignore the key entirely.
4. Take up to `maxMessages` candidates. For each, mint a new ackId, record an `AckLease(deadline_at = now() + ack_deadline_seconds)`, and (only for ordered subscriptions) add the message's `ordering_key` to `sub_ordering_blocked`.
5. Release the lock; return the messages.

`returnImmediately=true` returns whatever's available (possibly zero). Otherwise, if zero candidates are available, the call awaits an `asyncio.Event` (set whenever a `Publish` lands on the relevant topic) for up to 90 seconds before returning empty.

### 5.2 Acknowledge / ModifyAckDeadline

- `Acknowledge`: drop the lease; if the acked message had an ordering_key, remove the key from `sub_ordering_blocked` (unblocking later messages with that key).
- `ModifyAckDeadline` with positive `ackDeadlineSeconds`: extend `lease.deadline_at = now() + ackDeadlineSeconds`.
- `ModifyAckDeadline` with `ackDeadlineSeconds == 0`: NACK — drop the lease, push the message index onto `sub_nacked`, remove ordering-key block. Notify the subscription's deliverable Event so a waiting Pull wakes up.

### 5.3 Redelivery sweeper

A per-subscription `asyncio.Task` runs once per second:

- Walk `sub_leases[sub]` and reclaim any with `deadline_at < now()`. Treat reclaim identically to a NACK (push to `sub_nacked`, clear ordering-key block, notify deliverable Event).
- The sweeper is started when the first lease appears and idles cheaply when `sub_leases[sub]` is empty.

### 5.4 StreamingPull

Implemented as an async generator over the subscription's deliverable Event:

```python
async def StreamingPull(self, request_iterator, context):
    # First request carries subscription name + flow control + initial stream_ack_deadline_seconds
    # Subsequent requests carry ack_ids, modify_deadline_*, etc.
    sub = await self._authorize(first_request.subscription)
    asyncio.create_task(self._consume_client_messages(request_iterator, sub))
    while context.is_active():
        msgs = await self._pull_until(sub, max_count=remaining_flow_credit, timeout=...)
        if msgs:
            yield StreamingPullResponse(received_messages=[...])
```

Flow-control budget is tracked in-memory per stream as a single `(messages_outstanding, bytes_outstanding)` pair, decremented on yield and incremented on ack. The stream stops yielding new messages when either counter reaches its configured maximum (`max_outstanding_messages` / `max_outstanding_bytes` from the initial `StreamingPullRequest`); subsequent client requests adjust `stream_ack_deadline_seconds` and ack-list deltas, never the limits themselves (which the official client also sets only on stream open).

### 5.5 Seek

`Seek(time=t)`:

- Find the lowest message index `i` in `topic_messages[topic]` with `publish_time >= t` (binary search; messages are publish-time ordered).
- Atomically: drop all leases for the subscription (without re-NACKing — those messages no longer exist from the subscription's point of view), clear `sub_nacked`, clear `sub_ordering_blocked`, set `sub_cursor = i`.
- Effect: subscription rewinds (or fast-forwards) to the timestamp; subsequent pulls deliver messages from index `i` onward.

`Seek(snapshot=...)` returns `UNIMPLEMENTED` — snapshots are post-v1.

### 5.6 Ordering keys

When a subscription has `enableMessageOrdering=true` and `Publish` includes an `orderingKey`, the emulator preserves per-key order across redeliveries:

- A new message with key K is only delivered if no earlier message with key K is currently leased or in `sub_nacked`.
- If a leased message with key K NACKs or expires, it goes to the head of the K-ordered queue and blocks later K-keyed messages until acked.
- Messages with empty ordering_key are never blocked.

Subscriptions without ordering ignore the key entirely.

## 6. Storage

In-memory only for v1. The storage protocol mirrors Secret Manager's `Storage` ABC but does not include a `DiskStorage` implementation. Justification:

- Pub/Sub messages are inherently ephemeral; production retention is a sliding 7-day window, and emulator workflows almost always start from an empty backlog per test.
- Persisting topic message lists and subscription cursors raises non-trivial questions about message ID stability across restarts that aren't worth solving for the emulator.
- `PERSIST=1` continues to work for BigQuery / GCS / Secret Manager; the Pub/Sub service ignores it and logs an `info` line at startup so the user knows.

Adding `DiskStorage` later is mechanical and reversible if a workflow needs it.

## 7. Cross-service integration

### 7.1 StateHub events

`Publish` emits a `pubsub.message.published` event onto the StateHub bus:

```python
{
  "topic": "projects/p/topics/t",
  "message_id": "t-42",
  "attributes": {...},
  "size_bytes": len(data),
  "publish_time": "2026-04-29T..."
}
```

This is the local-only hook tests use to assert "the publisher actually published" without polling Pub/Sub. Push delivery (post-v1) will subscribe to this same event internally.

### 7.2 No GCS/BigQuery integration in v1

Pub/Sub-to-GCS and Pub/Sub-to-BigQuery subscriptions are listed as deferred (§2.3). The cross-service plumbing (StateHub) is in place; the actual subscription types are out of scope.

## 8. Error mapping

Internal exceptions → `grpc_error` codes (using the helper from Secret Manager):

| Internal | gRPC code | Reason |
|---|---|---|
| `TopicNotFound` / `SubscriptionNotFound` | `NOT_FOUND` | resource missing |
| `TopicAlreadyExists` / `SubscriptionAlreadyExists` | `ALREADY_EXISTS` | duplicate create |
| `InvalidName` (per Pub/Sub naming rules: 3–255 chars, `[A-Za-z][A-Za-z0-9-_.~+%]*`, no `goog` prefix) | `INVALID_ARGUMENT` | naming violation |
| `InvalidArgument` (bad ack_id format, missing required field) | `INVALID_ARGUMENT` | field validation |
| `Unimplemented` (IAM, snapshot Seek, schemas) | `UNIMPLEMENTED` | not yet supported |
| Uncaught | `INTERNAL` | fallback |

Naming validation lives in `names.py` and matches real Pub/Sub's regex; tests assert that gcloud-style names round-trip and that obvious garbage (empty, `goog`-prefixed, illegal characters) is rejected with `INVALID_ARGUMENT`.

## 9. Tests

### 9.1 Unit

Under `tests/unit/services/pubsub/`. One file per concern:

- `test_names.py` — name parser/validator + edge cases.
- `test_storage.py` — InMemoryStorage CRUD, lease lifecycle.
- `test_models.py` — record dataclasses + serializers.
- `test_servicer_topics.py` — Publisher RPCs against an in-process gRPC channel.
- `test_servicer_subscriptions.py` — Subscriber CRUD RPCs.
- `test_publish.py` — Publish allocates message IDs monotonically; populates `publishTime`; emits StateHub event.
- `test_pull.py` — unary Pull with empty/non-empty backlog, `returnImmediately`, `maxMessages`.
- `test_ack_modack.py` — ack drops the lease, modack extends, modack=0 NACKs and triggers redelivery.
- `test_redelivery.py` — expired leases redeliver after 1s sweep tick (the sweeper is patched to a faster cadence in tests).
- `test_ordering.py` — same-key messages serialize across NACKs.
- `test_streaming_pull.py` — bidirectional stream delivers, honors flow control, handles client-cancel.
- `test_seek.py` — seek-to-time rewinds and clears in-flight leases.
- `test_errors.py` — error envelope shapes for each `(internal exception → grpc code)` row.

### 9.2 Integration

`tests/integration/test_pubsub_integration.py` drives the real `google-cloud-pubsub` Python client against the in-process emulator. Coverage:

- Full publisher + subscriber lifecycle (create topic + subscription, publish 100 messages, pull-and-ack all).
- StreamingPull via `subscriber.subscribe(callback)` with a real `Future` returned by the client.
- Ordering keys via `PublisherOptions(enable_message_ordering=True)`.
- Seek-to-time round-trip.
- Resource-not-found and duplicate-create error mapping.

The existing `emulator` fixture (in `tests/integration/conftest.py`) is extended to include `pubsub` in the default service list.

## 10. PR phasing

Per user direction: **single PR**. Justified despite the project's <500-LOC ceiling because Pub/Sub's components (publisher, subscriber, delivery, streaming) are tightly interdependent — a partial implementation would be unusable, and reviewers benefit from seeing the delivery-semantics state machine alongside its tests in one diff. Estimated ~2000 LOC production + ~1500 LOC tests + docs.

Branch: `feat/pubsub-service`. PR description will explicitly call out the size override and link this spec.

## 11. Documentation deliverables

Per `docs/development/adding-a-service.md` §6:

- `docs/services/pubsub.md` — user-facing usage doc with elevator pitch, what's emulated, what's not, connection recipe, examples (publish, pull, streaming pull, ordering, seek), limits & quirks.
- `docs/architecture/pubsub.md` — internals deep-dive: at-a-glance, wire & port, storage model, request lifecycle, delivery state machine (the §5 state diagram), error mapping, tests, internals-level limitations.
- `README.md` — add row to "Services at a glance" table; update default-ports list.
- `ROADMAP.md` — move Pub/Sub from Planned → delete (it now lives in README); add the deferred items from §2.3 to "Per-service follow-ups → Pub/Sub".
- `docs/deployment.md` — add 8085 to the default-ports table.
- `CHANGELOG.md` — `[Unreleased] Added` entry.

## 12. Internals-level limitations (carried forward to architecture doc)

- **In-memory only**, even with `PERSIST=1`. Messages and subscription cursors are lost across restarts.
- **Topic backlog grows unbounded** for the process lifetime. Real Pub/Sub retains messages for 7 days max; the emulator retains until the process exits or the subscription acks them.
- **Filters are not evaluated.** Every published message is delivered to every matching subscription.
- **Push subscriptions are no-ops.** `pushConfig` is stored and reflected on `GetSubscription`, but the emulator never POSTs to the URL.
- **Exactly-once delivery is downgraded to at-least-once.** `enableExactlyOnceDelivery=true` is accepted on the wire, logged, and otherwise ignored.
- **Single-process delivery.** The whole emulator runs in one Python process; horizontal scale-out is not relevant for emulator workloads.
