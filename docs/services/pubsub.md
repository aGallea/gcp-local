# Pub/Sub emulator

gcp-local's Pub/Sub service emulates the Google Cloud Pub/Sub gRPC API. The official `google-cloud-pubsub` Python client works against it with no code changes — it reads the standard `PUBSUB_EMULATOR_HOST` environment variable and routes there automatically.

Default port: **8085** (the canonical Pub/Sub emulator port). The wire protocol is **gRPC**.

---

## What's emulated

**Publisher (`google.pubsub.v1.Publisher`)**

- `CreateTopic`, `GetTopic`, `UpdateTopic` (labels only), `DeleteTopic`
- `ListTopics`, `ListTopicSubscriptions` — both with `pageSize` + `pageToken` paging
- `Publish` — single-RPC batch of messages; the server stamps a monotonic per-topic `messageId` and `publishTime`, and returns the IDs in publish order

**Subscriber (`google.pubsub.v1.Subscriber`)**

- `CreateSubscription`, `GetSubscription`, `UpdateSubscription` (labels and `ackDeadlineSeconds` only), `DeleteSubscription`
- `ListSubscriptions` — with paging
- `Pull` — unary blocking pull; honors `maxMessages` and the `returnImmediately` field (the deprecated flag is treated as a 0-second wait when `true`, otherwise a short long-poll up to 90s)
- `StreamingPull` — bidirectional stream with per-stream flow control (`stream_ack_deadline_seconds`, `max_outstanding_messages`, `max_outstanding_bytes`); honors mid-stream `modify_deadline_*` and `ack_ids` deltas
- `Acknowledge`, `ModifyAckDeadline` — per `ackId`
- `Seek` — by `time` only

**Delivery semantics**

- **At-least-once delivery.** Pulled messages mint an `ackId` with a per-subscription deadline; an unacked message whose deadline expires is redelivered.
- **Per-subscription redelivery sweeper** — runs every 1 second and reclaims expired leases.
- **Message ordering.** Subscriptions created with `enableMessageOrdering=true` honor `orderingKey`: messages with the same key are delivered in publish order, and a NACK or redelivery on an ordered message blocks later messages with the same key until the in-flight one is acked.
- **Seek-to-time.** `Seek(time=t)` rewinds (or fast-forwards) the subscription cursor to the first message with `publishTime >= t`, drops in-flight leases, and clears any NACK queue.

**Project namespacing.** `projects/<project>/topics/<name>` and `projects/<project>/subscriptions/<name>` are the primary keys; different projects can hold the same topic/subscription names independently.

---

## What's not emulated (v1)

The fields below are accepted on the wire (so client validation does not fail) and stored on the resource — but the emulator does not act on them:

- **`Subscription.filter`** — stored, never evaluated. Every published message is delivered to every matching subscription regardless of the filter expression.
- **`Subscription.deadLetterPolicy`** — stored, never triggered. Messages do not move to a dead-letter topic after N redeliveries.
- **`Subscription.retryPolicy`** — stored. The emulator uses a fixed 1-second redelivery sweep regardless of `minimumBackoff` / `maximumBackoff`.
- **`Subscription.expirationPolicy`** — stored. Subscriptions are never auto-deleted.
- **`Subscription.messageRetentionDuration`** — stored. The emulator retains messages until ack or process exit (no TTL).
- **`Subscription.enableExactlyOnceDelivery`** — accepted on the wire and downgraded to at-least-once. The emulator logs a warning at create time; clients see no other change.
- **`Topic.messageStoragePolicy`**, **`Topic.kmsKeyName`**, **`Topic.schemaSettings`** — stored, no enforcement.

These are deferred entirely (return `UNIMPLEMENTED` or are simply absent):

- **Schema service** — `SchemaService` RPCs are not registered. Calls return gRPC `UNIMPLEMENTED`.
- **Snapshots** — `CreateSnapshot`, `ListSnapshots`, `GetSnapshot`, `DeleteSnapshot`, and `Seek(snapshot=…)` return `UNIMPLEMENTED`.
- **BigQuery and Cloud Storage subscriptions** — not supported.
- **Detached subscriptions** — `DetachSubscription` returns `UNIMPLEMENTED`.
- **IAM** — `GetIamPolicy`, `SetIamPolicy`, `TestIamPermissions` return `UNIMPLEMENTED`.
- **Persistence** — Pub/Sub state is in-memory only, even with `PERSIST=1` (see [Limits & quirks](#limits--quirks)).

---

## Connecting

The official `google-cloud-pubsub` client reads `PUBSUB_EMULATOR_HOST` natively. Setting that environment variable before constructing the client is the recommended path — no code changes needed:

```bash
export PUBSUB_EMULATOR_HOST=localhost:8085
```

```python
import os
os.environ["PUBSUB_EMULATOR_HOST"] = "localhost:8085"

from google.cloud import pubsub_v1

publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()

topic_path = publisher.topic_path("my-project", "my-topic")
publisher.create_topic(request={"name": topic_path})
```

When `PUBSUB_EMULATOR_HOST` is set, the client opens an insecure gRPC channel to that address and skips authentication — no `AnonymousCredentials` boilerplate is required.

### Port override

Override the default port with `PUBSUB_EMULATOR_PORT` before starting the emulator:

```bash
PUBSUB_EMULATOR_PORT=18085 python -m gcp_local
```

Then point the client at `localhost:18085` via `PUBSUB_EMULATOR_HOST`.

---

## Quickstart

```python
import os
os.environ["PUBSUB_EMULATOR_HOST"] = "localhost:8085"

from google.cloud import pubsub_v1

PROJECT = "my-project"
publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()

topic_path = publisher.topic_path(PROJECT, "events")
sub_path = subscriber.subscription_path(PROJECT, "events-sub")

# 1. Create the topic and subscription.
publisher.create_topic(request={"name": topic_path})
subscriber.create_subscription(
    request={"name": sub_path, "topic": topic_path, "ack_deadline_seconds": 10}
)

# 2. Publish a message.
future = publisher.publish(topic_path, b"hello world", source="quickstart")
message_id = future.result(timeout=5)
print("published:", message_id)

# 3. Pull and ack.
response = subscriber.pull(
    request={"subscription": sub_path, "max_messages": 10},
    timeout=5,
)
ack_ids = [m.ack_id for m in response.received_messages]
for m in response.received_messages:
    print("got:", m.message.data, dict(m.message.attributes))
subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})
```

---

## Examples

The examples below assume `PUBSUB_EMULATOR_HOST` is exported and `PROJECT = "my-project"`.

### Publish (with attributes)

```python
from google.cloud import pubsub_v1

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path("my-project", "events")

future = publisher.publish(
    topic_path,
    data=b'{"event": "click"}',
    user_id="42",
    region="us-east1",
)
print(future.result())  # message_id, e.g. "events-1"
```

`publisher.publish` returns a `Future`; call `.result()` to block until the server confirms the publish (and to surface any error).

### Pull and ack (unary)

```python
from google.cloud import pubsub_v1

subscriber = pubsub_v1.SubscriberClient()
sub_path = subscriber.subscription_path("my-project", "events-sub")

response = subscriber.pull(
    request={"subscription": sub_path, "max_messages": 100},
    timeout=10,
)

ack_ids = []
for received in response.received_messages:
    print(received.message.message_id, received.message.data)
    ack_ids.append(received.ack_id)

if ack_ids:
    subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})
```

To reject a message and trigger immediate redelivery, send `modify_ack_deadline` with `ack_deadline_seconds=0`:

```python
subscriber.modify_ack_deadline(
    request={
        "subscription": sub_path,
        "ack_ids": [received.ack_id],
        "ack_deadline_seconds": 0,
    }
)
```

### Streaming pull (`subscriber.subscribe(callback)`)

The streaming-pull path is what the high-level `subscriber.subscribe(...)` callback API uses internally:

```python
from concurrent.futures import TimeoutError
from google.cloud import pubsub_v1

subscriber = pubsub_v1.SubscriberClient()
sub_path = subscriber.subscription_path("my-project", "events-sub")

def handle(message):
    print("received:", message.message_id, message.data)
    message.ack()

streaming_pull_future = subscriber.subscribe(sub_path, callback=handle)

try:
    streaming_pull_future.result(timeout=30)
except TimeoutError:
    streaming_pull_future.cancel()
    streaming_pull_future.result()
```

The emulator honors per-stream flow control: `flow_control=pubsub_v1.types.FlowControl(max_messages=50, max_bytes=10 * 1024 * 1024)` caps the number of in-flight (pulled-but-unacked) messages and bytes per stream. Mid-stream `modify_deadline_*` and `ack_ids` deltas are processed; flow-control limits are read from the initial `StreamingPullRequest` and not adjusted afterwards (which matches the official client's behavior).

### Ordering keys

Ordering requires three things: (1) the topic created normally, (2) the subscription created with `enable_message_ordering=True`, and (3) the publisher constructed with `PublisherOptions(enable_message_ordering=True)`.

```python
from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.types import PublisherOptions

PROJECT = "my-project"
publisher = pubsub_v1.PublisherClient(
    publisher_options=PublisherOptions(enable_message_ordering=True),
)
subscriber = pubsub_v1.SubscriberClient()

topic_path = publisher.topic_path(PROJECT, "ordered")
sub_path = subscriber.subscription_path(PROJECT, "ordered-sub")

publisher.create_topic(request={"name": topic_path})
subscriber.create_subscription(
    request={
        "name": sub_path,
        "topic": topic_path,
        "enable_message_ordering": True,
    }
)

# Messages with the same ordering key are delivered in publish order;
# a NACK on one blocks later same-key messages until it is redelivered + acked.
for i in range(5):
    publisher.publish(topic_path, f"msg-{i}".encode(), ordering_key="user-42").result()
```

Messages with empty `ordering_key` are never blocked. Messages with different keys can be delivered concurrently. Subscriptions created without `enable_message_ordering=True` ignore the key entirely (delivery order is not preserved).

### Seek to a timestamp

```python
import time
from google.protobuf import timestamp_pb2
from google.cloud import pubsub_v1

publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()
sub_path = subscriber.subscription_path("my-project", "events-sub")

# Capture a timestamp, publish more messages, then rewind to it.
checkpoint = timestamp_pb2.Timestamp()
checkpoint.FromSeconds(int(time.time()))

# ... publish more messages, pull-and-ack some ...

subscriber.seek(request={"subscription": sub_path, "time": checkpoint})
# The next pull starts from the first message whose publish_time >= checkpoint;
# any in-flight leases are dropped and the NACK queue is cleared.
```

`Seek(time=…)` is the only supported variant. `Seek(snapshot=…)` returns `UNIMPLEMENTED`.

---

## Push subscriptions

The emulator delivers messages to subscriptions configured with `push_config.push_endpoint`. When a message lands on the topic, a per-subscription background pump POSTs a JSON envelope matching real Pub/Sub's wire format to the endpoint:

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

`attributes` is omitted when the published message has none; `orderingKey` is omitted when empty. The request is `POST` with `Content-Type: application/json` and `User-Agent: gcp-local-pubsub-push/0`.

**Acks via HTTP status:**

- `2xx` → message acked.
- Non-`2xx`, connection error, or timeout (default 30 s) → message NACKed; the existing ack-deadline redelivery sweeper redrives on the next pump tick.

**Per-subscription serial delivery.** The pump sends one message at a time. Two messages with the same `orderingKey` are delivered in publish order: the second waits until the first is acked. Across different ordering keys (or with ordering disabled), the pump still serializes per subscription — real Pub/Sub may parallelize, but the emulator does not.

**Endpoint changes.** `UpdateSubscription` with `push_config` in the field mask hot-swaps the pump: clearing `push_endpoint` stops delivery; pointing at a new URL restarts the pump targeting the new endpoint. The same field mask supports flipping a pull subscription into a push subscription and back.

**Not emitted (deferred):**

- `pushConfig.oidcToken` — stored on the resource, but no `Authorization` header is added to the POST. Real Pub/Sub signs a JWT here.
- `pushConfig.attributes` — stored, but not echoed back as HTTP headers (`x-goog-version` etc.).
- `subscription.retryPolicy.minimumBackoff` / `maximumBackoff` — stored, not honored. NACK redelivers on the next pump tick (no exponential backoff).
- `noWrapper` mode — always send the wrapped envelope.

### Quickstart

```python
from google.cloud import pubsub_v1

publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()

topic_path = publisher.topic_path("my-project", "events")
sub_path = subscriber.subscription_path("my-project", "events-push-sub")

publisher.create_topic(request={"name": topic_path})
subscriber.create_subscription(
    request={
        "name": sub_path,
        "topic": topic_path,
        "push_config": {"push_endpoint": "http://localhost:9999/push"},
        "ack_deadline_seconds": 10,
    }
)

# Anything you publish from here onwards is POSTed to localhost:9999/push.
publisher.publish(topic_path, b"hello", region="us-east1").result()
```

---

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `PUBSUB_EMULATOR_HOST` | — | Consumed by `google-cloud-pubsub`; set to `localhost:8085` (or custom port) |
| `PUBSUB_EMULATOR_PORT` | `8085` | Port the Pub/Sub gRPC server listens on |
| `PERSIST` | `0` | **Ignored** by Pub/Sub. The service is in-memory only; an info-level log line is emitted at startup so the user knows |

---

## Reset semantics

`POST /_emulator/reset?service=pubsub`

Drops all topics, subscriptions, message backlogs, in-flight leases, and the per-topic message-ID counter. Useful between test cases.

```bash
curl -X POST http://localhost:4510/_emulator/reset?service=pubsub
```

Note: the reset endpoint is served by the admin API on port **4510**, not on the Pub/Sub gRPC port (8085). Sending it to 8085 will fail.

---

## Limits & quirks

**In-memory only.** Pub/Sub state never persists across restarts, even with `PERSIST=1`. Topics, subscriptions, and message backlogs are gone the moment the process exits. Production Pub/Sub messages are inherently transient (sliding 7-day window) and emulator workflows almost always start from an empty backlog per test, so the trade-off is intentional. The other services (BigQuery / GCS / Secret Manager) honor `PERSIST=1` as before.

**Topic backlog grows unbounded.** Real Pub/Sub retains messages for up to 7 days; the emulator retains them until the process exits or every subscription has acked them. Long-running emulator processes that publish heavily will accumulate memory. Reset between tests, or restart the container if it matters.

**Filters are not evaluated.** A subscription created with `filter='attributes.region = "us-east1"'` will receive every message, regardless of attributes. The filter string round-trips on `GetSubscription`, but it has no effect on delivery.

**Exactly-once delivery is downgraded to at-least-once.** `enable_exactly_once_delivery=True` is accepted, logged, and otherwise ignored. Plan for at-least-once redelivery in test code.

**Snapshots are not implemented.** `CreateSnapshot`, `ListSnapshots`, `GetSnapshot`, `DeleteSnapshot`, and `Seek(snapshot=…)` all return `UNIMPLEMENTED`. Use `Seek(time=…)` for replay.

**`returnImmediately` long-poll is capped at 90 seconds.** When `returnImmediately=false` (or unset) and the backlog is empty, `Pull` waits up to 90 seconds for a publish before returning empty. The official client's default flow uses StreamingPull and never hits this path.

**No authentication.** Every caller can publish to and pull from every topic in every project. Use `PUBSUB_EMULATOR_HOST` to avoid sending real credentials to the emulator (the env var disables authentication client-side).

**Single-process.** The whole emulator runs in one Python process; horizontal scale-out is not relevant. All locks are `asyncio.Lock`s, not OS-level mutexes.

**`messageId` shape.** The emulator stamps IDs as `<topic_id>-<n>` (monotonic per topic). Real Pub/Sub uses opaque 16+ digit IDs. Test code that asserts on the exact ID shape will need to relax that assertion or switch to "ID is non-empty".
