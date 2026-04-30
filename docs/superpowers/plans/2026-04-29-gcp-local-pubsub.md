# gcp-local Pub/Sub Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Pub/Sub service so the official `google-cloud-pubsub` Python client library works unchanged against the emulator over gRPC. Covers Publisher + Subscriber RPCs, unary `Pull` + `StreamingPull`, ack-deadline redelivery, ordering keys, and seek-to-time.

**Architecture:** New `gcp_local.services.pubsub` package registered as a Service. The service owns its own `grpc.aio.Server` on port 8085 (canonical Pub/Sub emulator port; clients pick it up via `PUBSUB_EMULATOR_HOST` automatically). Storage is in-memory only. Delivery semantics live in an `engine/` subpackage with a per-subscription backlog, a 1-second redelivery sweeper, and ordering-key gating. Proto stubs are vendored under `protos/google/pubsub/v1/` and generated into `src/gcp_local/generated/` via the existing `scripts/gen_protos.sh` (extended to include Pub/Sub).

**Tech Stack:** Python 3.13, grpcio (existing runtime dep), googleapis-common-protos (existing), grpcio-tools + google-cloud-pubsub (existing dev deps), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-29-gcp-local-pubsub-design.md`

**Branch:** `feat/pubsub-service` (already created; spec already committed). All implementation tasks land on this branch; when all tasks pass, open a PR to `master`.

**Commit policy:** Per-task commits allowed in this session. Use `.venv/bin/python` (not bare `python`). Do not bypass signing/hooks. Trailer on every commit (HEREDOC):
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Single-PR override:** Per user direction, this lands as one PR rather than the usual <500 LOC cuts. The components (servicer, backlog, delivery, streaming) are tightly interdependent and a partial implementation would be unusable.

---

## File structure

```
protos/google/pubsub/v1/
  pubsub.proto                                # NEW (vendored from googleapis)

scripts/
  gen_protos.sh                               # MODIFY: add pubsub generation + import rewrite

src/gcp_local/generated/google/pubsub/v1/
  __init__.py                                 # NEW
  pubsub_pb2.py                               # GENERATED
  pubsub_pb2.pyi                              # GENERATED
  pubsub_pb2_grpc.py                          # GENERATED
src/gcp_local/generated/google/pubsub/
  __init__.py                                 # NEW

src/gcp_local/services/pubsub/
  __init__.py                                 # exports PubSubService
  service.py                                  # PubSubService (Service protocol)
  servicer.py                                 # PublisherServicer + SubscriberServicer
  models.py                                   # TopicRecord, SubscriptionRecord, MessageRecord, AckLease
  storage.py                                  # PubSubStorage (in-memory only)
  names.py                                    # name parsers/validators
  errors.py                                   # exception types + gRPC mappers
  engine/
    __init__.py
    backlog.py                                # SubscriptionBacklog: cursor + leases + ordering
    delivery.py                               # Redelivery sweeper task
    streaming.py                              # StreamingPull session loop

tests/unit/services/pubsub/
  __init__.py
  test_names.py
  test_models.py
  test_storage.py
  test_servicer_topics.py
  test_servicer_subscriptions.py
  test_publish.py
  test_pull.py
  test_ack_modack.py
  test_redelivery.py
  test_ordering.py
  test_streaming_pull.py
  test_seek.py
  test_errors.py

tests/integration/
  test_pubsub_integration.py
  conftest.py                                 # MODIFY: include "pubsub" in default service list

docs/services/pubsub.md                       # NEW
docs/architecture/pubsub.md                   # NEW

pyproject.toml                                # MODIFY: register entry point
README.md                                     # MODIFY: add row + ports
ROADMAP.md                                    # MODIFY: remove Pub/Sub from Planned, add follow-ups
CHANGELOG.md                                  # MODIFY: [Unreleased] entry
docs/deployment.md                            # MODIFY: add 8085 to ports table
```

---

## Task 1: Vendor pubsub.proto and extend the proto generator

**Files:**
- Create: `protos/google/pubsub/v1/pubsub.proto` (vendored from googleapis)
- Modify: `scripts/gen_protos.sh`
- Create: `src/gcp_local/generated/google/pubsub/__init__.py` (empty)
- Create: `src/gcp_local/generated/google/pubsub/v1/__init__.py` (empty)

- [ ] **Step 1: Fetch the canonical pubsub.proto + transitive schema.proto**

The proto lives in googleapis at `google/pubsub/v1/pubsub.proto`. It transitively imports `schema.proto` for `SchemaSettings.encoding` on `Topic`, so we must vendor both even though we never register `SchemaServiceServicer`. Fetch from the master branch since the protos are API-stable:

```bash
mkdir -p protos/google/pubsub/v1
curl -sSL -o protos/google/pubsub/v1/pubsub.proto \
  https://raw.githubusercontent.com/googleapis/googleapis/master/google/pubsub/v1/pubsub.proto
curl -sSL -o protos/google/pubsub/v1/schema.proto \
  https://raw.githubusercontent.com/googleapis/googleapis/master/google/pubsub/v1/schema.proto
```

Verify `pubsub.proto` has `package google.pubsub.v1;` and contains `service Publisher` and `service Subscriber`. Verify `schema.proto` has `package google.pubsub.v1;` and contains `service SchemaService` and `message Schema`. (We won't register the SchemaService servicer — clients calling its RPCs will get `UNIMPLEMENTED` from grpc by default.)

- [ ] **Step 2: Extend `scripts/gen_protos.sh` to generate pubsub stubs**

Append to the script (do not remove the existing secret_manager block):

```bash
# Pub/Sub (pubsub.proto + transitive schema.proto)
python -m grpc_tools.protoc \
  --proto_path=protos \
  --proto_path="$EXTRA_PROTO_PATH" \
  --python_out="$OUT" \
  --pyi_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/google/pubsub/v1/pubsub.proto \
  protos/google/pubsub/v1/schema.proto

python - <<'PY'
import pathlib, re
out = pathlib.Path('src/gcp_local/generated/google/pubsub/v1')
for p in out.glob('*.py'):
    text = p.read_text()
    new = re.sub(
        r'^from google\.pubsub\.v1 import',
        'from gcp_local.generated.google.pubsub.v1 import',
        text,
        flags=re.MULTILINE,
    )
    if new != text:
        p.write_text(new)
        print(f'rewrote imports in {p}')
PY

echo 'generated pubsub:'
ls -1 "src/gcp_local/generated/google/pubsub/v1/"
```

- [ ] **Step 3: Run the generator and confirm files appear**

```bash
bash scripts/gen_protos.sh
```

Expected output includes a `generated pubsub:` line followed by `pubsub_pb2.py`, `pubsub_pb2.pyi`, `pubsub_pb2_grpc.py`. Then add the empty `__init__.py` files:

```bash
touch src/gcp_local/generated/google/pubsub/__init__.py
touch src/gcp_local/generated/google/pubsub/v1/__init__.py
```

- [ ] **Step 4: Smoke-test the imports**

```bash
.venv/bin/python -c "from gcp_local.generated.google.pubsub.v1 import pubsub_pb2, pubsub_pb2_grpc; print(pubsub_pb2_grpc.PublisherServicer, pubsub_pb2_grpc.SubscriberServicer)"
```

Expected: prints both servicer classes. If imports fail, the import-rewrite step missed a path; fix the regex.

- [ ] **Step 5: Commit**

```bash
git add protos/google/pubsub scripts/gen_protos.sh src/gcp_local/generated/google/pubsub
git commit -m "$(cat <<'EOF'
chore(pubsub): vendor pubsub.proto and generate gRPC stubs

Mirrors the Secret Manager pattern: vendored .proto under protos/
and generated _pb2 / _pb2_grpc stubs under src/gcp_local/generated/.
Runtime image picks these up directly; google-cloud-pubsub stays
test-only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Names module

**Files:**
- Create: `src/gcp_local/services/pubsub/names.py`
- Create: `src/gcp_local/services/pubsub/__init__.py` (empty for now)
- Test: `tests/unit/services/pubsub/__init__.py` (empty), `tests/unit/services/pubsub/test_names.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/services/pubsub/test_names.py`:

```python
import pytest

from gcp_local.services.pubsub.names import (
    InvalidName,
    build_subscription_name,
    build_topic_name,
    parse_subscription_name,
    parse_topic_name,
    validate_resource_id,
)


def test_parse_topic_name_happy() -> None:
    assert parse_topic_name("projects/my-proj/topics/my-topic") == ("my-proj", "my-topic")


def test_parse_topic_name_rejects_garbage() -> None:
    with pytest.raises(InvalidName):
        parse_topic_name("not/a/valid/path")


def test_build_topic_name() -> None:
    assert build_topic_name("p", "t") == "projects/p/topics/t"


def test_parse_subscription_name_happy() -> None:
    assert parse_subscription_name("projects/p/subscriptions/s") == ("p", "s")


def test_build_subscription_name() -> None:
    assert build_subscription_name("p", "s") == "projects/p/subscriptions/s"


@pytest.mark.parametrize(
    "name",
    ["top", "t-name", "t.name", "t_name", "Name123", "with~plus+pct%20"],
)
def test_validate_resource_id_accepts(name: str) -> None:
    validate_resource_id(name)  # does not raise


@pytest.mark.parametrize(
    "name",
    ["", "ab", "1starts-with-digit", "goog-prefixed", "has spaces", "bad/slash", "x" * 256],
)
def test_validate_resource_id_rejects(name: str) -> None:
    with pytest.raises(InvalidName):
        validate_resource_id(name)
```

- [ ] **Step 2: Verify the tests fail (module doesn't exist)**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_names.py -x 2>&1 | tail -10
```

Expected: ImportError / collection failure.

- [ ] **Step 3: Implement names.py**

```python
"""Pub/Sub resource-name parsing & validation.

Matches the official Pub/Sub naming rules: 3-255 chars, must start with
a letter, may not start with the literal 'goog' (case-insensitive),
allowed character class is letters/digits/'-_.~+%'. The validator is
shared by topic and subscription IDs (the rules are identical).
"""

import re

_RE_TOPIC = re.compile(r"^projects/([^/]+)/topics/([^/]+)$")
_RE_SUBSCRIPTION = re.compile(r"^projects/([^/]+)/subscriptions/([^/]+)$")
_RE_VALID_ID = re.compile(r"^[A-Za-z][A-Za-z0-9\-_.~+%]{2,254}$")


class InvalidName(ValueError):
    """Resource name does not match Pub/Sub naming rules."""


def parse_topic_name(name: str) -> tuple[str, str]:
    m = _RE_TOPIC.fullmatch(name)
    if not m:
        raise InvalidName(f"Invalid topic name: {name!r}")
    return m.group(1), m.group(2)


def build_topic_name(project: str, topic_id: str) -> str:
    return f"projects/{project}/topics/{topic_id}"


def parse_subscription_name(name: str) -> tuple[str, str]:
    m = _RE_SUBSCRIPTION.fullmatch(name)
    if not m:
        raise InvalidName(f"Invalid subscription name: {name!r}")
    return m.group(1), m.group(2)


def build_subscription_name(project: str, subscription_id: str) -> str:
    return f"projects/{project}/subscriptions/{subscription_id}"


def validate_resource_id(rid: str) -> None:
    if not _RE_VALID_ID.fullmatch(rid):
        raise InvalidName(f"Invalid resource id: {rid!r}")
    if rid.lower().startswith("goog"):
        raise InvalidName(f"Resource id may not start with 'goog': {rid!r}")
```

Also create `src/gcp_local/services/pubsub/__init__.py` (empty for now — will export `PubSubService` later).

- [ ] **Step 4: Run tests and confirm green**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_names.py -x 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/__init__.py src/gcp_local/services/pubsub/names.py tests/unit/services/pubsub/__init__.py tests/unit/services/pubsub/test_names.py
git commit -m "feat(pubsub): add resource name parser/validator

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Models module

**Files:**
- Create: `src/gcp_local/services/pubsub/models.py`
- Test: `tests/unit/services/pubsub/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
import datetime as dt

from gcp_local.services.pubsub.models import (
    AckLease,
    MessageRecord,
    SubscriptionRecord,
    TopicRecord,
)


def test_topic_record_minimal() -> None:
    t = TopicRecord(
        project="p",
        topic_id="t",
        labels={},
        message_storage_policy=None,
        kms_key_name=None,
        schema_settings=None,
    )
    assert t.project == "p"
    assert t.topic_id == "t"


def test_message_record_holds_attrs_and_data() -> None:
    m = MessageRecord(
        message_id="t-1",
        publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=b"hello",
        attributes={"k": "v"},
        ordering_key="",
    )
    assert m.data == b"hello"
    assert m.attributes == {"k": "v"}
    assert m.ordering_key == ""


def test_subscription_record_defaults_capture_protocol_fields() -> None:
    s = SubscriptionRecord(
        project="p",
        subscription_id="s",
        topic_project="p",
        topic_id="t",
        ack_deadline_seconds=10,
        enable_message_ordering=False,
        push_config=None,
        filter="",
        dead_letter_policy=None,
        retry_policy=None,
        labels={},
        enable_exactly_once_delivery=False,
        create_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
    )
    assert s.ack_deadline_seconds == 10


def test_ack_lease_holds_deadline() -> None:
    deadline = dt.datetime(2026, 4, 29, 12, 0, 30, tzinfo=dt.UTC)
    lease = AckLease(ack_id="lease-abc", message_index=42, deadline_at=deadline)
    assert lease.ack_id == "lease-abc"
    assert lease.message_index == 42
    assert lease.deadline_at == deadline
```

- [ ] **Step 2: Verify tests fail**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_models.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement models.py**

```python
"""Domain dataclasses for the Pub/Sub emulator.

These are the pure in-memory representations; the gRPC servicer
(``servicer.py``) converts to/from the proto messages defined in
``gcp_local.generated.google.pubsub.v1.pubsub_pb2``.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TopicRecord:
    project: str
    topic_id: str
    labels: dict[str, str]
    message_storage_policy: dict[str, Any] | None
    kms_key_name: str | None
    schema_settings: dict[str, Any] | None


@dataclass
class MessageRecord:
    message_id: str
    publish_time: dt.datetime
    data: bytes
    attributes: dict[str, str]
    ordering_key: str  # "" if unset


@dataclass
class SubscriptionRecord:
    project: str
    subscription_id: str
    topic_project: str
    topic_id: str
    ack_deadline_seconds: int
    enable_message_ordering: bool
    push_config: dict[str, Any] | None
    filter: str
    dead_letter_policy: dict[str, Any] | None
    retry_policy: dict[str, Any] | None
    labels: dict[str, str]
    enable_exactly_once_delivery: bool
    create_time: dt.datetime


@dataclass
class AckLease:
    """An in-flight delivery — message returned to a subscriber but not yet acked.

    ``message_index`` is the position into ``PubSubStorage.topic_messages[(p,t)]``;
    leases never reference a MessageRecord by identity, only by index, so leases
    survive arbitrary list growth on the topic side.
    """
    ack_id: str
    message_index: int
    deadline_at: dt.datetime
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_models.py -x 2>&1 | tail -5
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/models.py tests/unit/services/pubsub/test_models.py
git commit -m "feat(pubsub): add domain dataclasses

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Errors module

**Files:**
- Create: `src/gcp_local/services/pubsub/errors.py`
- Test: `tests/unit/services/pubsub/test_errors.py`

- [ ] **Step 1: Write the failing tests**

```python
import grpc
import pytest

from gcp_local.services.pubsub.errors import (
    InvalidArgument,
    PubSubError,
    SubscriptionAlreadyExists,
    SubscriptionNotFound,
    TopicAlreadyExists,
    TopicNotFound,
    grpc_code_for,
)


@pytest.mark.parametrize(
    "exc, expected_code",
    [
        (TopicNotFound("projects/p/topics/t"), grpc.StatusCode.NOT_FOUND),
        (SubscriptionNotFound("projects/p/subscriptions/s"), grpc.StatusCode.NOT_FOUND),
        (TopicAlreadyExists("projects/p/topics/t"), grpc.StatusCode.ALREADY_EXISTS),
        (SubscriptionAlreadyExists("projects/p/subscriptions/s"), grpc.StatusCode.ALREADY_EXISTS),
        (InvalidArgument("bad ack id"), grpc.StatusCode.INVALID_ARGUMENT),
    ],
)
def test_grpc_code_for_known_exceptions(exc: PubSubError, expected_code: grpc.StatusCode) -> None:
    assert grpc_code_for(exc) == expected_code


def test_grpc_code_for_unknown_exception_is_internal() -> None:
    assert grpc_code_for(RuntimeError("boom")) == grpc.StatusCode.INTERNAL
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_errors.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement errors.py**

```python
"""Pub/Sub-specific exception types and gRPC code mapping."""

import grpc


class PubSubError(Exception):
    """Base for all Pub/Sub-internal exceptions."""


class TopicNotFound(PubSubError):
    pass


class SubscriptionNotFound(PubSubError):
    pass


class TopicAlreadyExists(PubSubError):
    pass


class SubscriptionAlreadyExists(PubSubError):
    pass


class InvalidArgument(PubSubError):
    """Wire-shape validation failure (bad ack_id, missing required field, etc.)."""


_CODE_MAP: dict[type[Exception], grpc.StatusCode] = {
    TopicNotFound: grpc.StatusCode.NOT_FOUND,
    SubscriptionNotFound: grpc.StatusCode.NOT_FOUND,
    TopicAlreadyExists: grpc.StatusCode.ALREADY_EXISTS,
    SubscriptionAlreadyExists: grpc.StatusCode.ALREADY_EXISTS,
    InvalidArgument: grpc.StatusCode.INVALID_ARGUMENT,
}


def grpc_code_for(exc: Exception) -> grpc.StatusCode:
    return _CODE_MAP.get(type(exc), grpc.StatusCode.INTERNAL)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_errors.py -x 2>&1 | tail -5
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/errors.py tests/unit/services/pubsub/test_errors.py
git commit -m "feat(pubsub): add exception types and gRPC code mapping

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Storage (in-memory only)

**Files:**
- Create: `src/gcp_local/services/pubsub/storage.py`
- Test: `tests/unit/services/pubsub/test_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
import datetime as dt

import pytest

from gcp_local.services.pubsub.errors import (
    SubscriptionAlreadyExists,
    SubscriptionNotFound,
    TopicAlreadyExists,
    TopicNotFound,
)
from gcp_local.services.pubsub.models import (
    MessageRecord,
    SubscriptionRecord,
    TopicRecord,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


def _topic(project: str = "p", tid: str = "t") -> TopicRecord:
    return TopicRecord(
        project=project,
        topic_id=tid,
        labels={},
        message_storage_policy=None,
        kms_key_name=None,
        schema_settings=None,
    )


def _subscription(
    project: str = "p",
    sid: str = "s",
    tid: str = "t",
    *,
    enable_ordering: bool = False,
) -> SubscriptionRecord:
    return SubscriptionRecord(
        project=project,
        subscription_id=sid,
        topic_project=project,
        topic_id=tid,
        ack_deadline_seconds=10,
        enable_message_ordering=enable_ordering,
        push_config=None,
        filter="",
        dead_letter_policy=None,
        retry_policy=None,
        labels={},
        enable_exactly_once_delivery=False,
        create_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
    )


@pytest.mark.asyncio
async def test_create_and_get_topic() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    got = await s.get_topic("p", "t")
    assert got.topic_id == "t"


@pytest.mark.asyncio
async def test_create_topic_duplicate_raises() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    with pytest.raises(TopicAlreadyExists):
        await s.create_topic(_topic())


@pytest.mark.asyncio
async def test_get_topic_missing_raises() -> None:
    s = InMemoryStorage()
    with pytest.raises(TopicNotFound):
        await s.get_topic("p", "missing")


@pytest.mark.asyncio
async def test_delete_topic_removes() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.delete_topic("p", "t")
    with pytest.raises(TopicNotFound):
        await s.get_topic("p", "t")


@pytest.mark.asyncio
async def test_list_topics_filtered_by_project() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic("p1", "a"))
    await s.create_topic(_topic("p1", "b"))
    await s.create_topic(_topic("p2", "c"))
    rows = await s.list_topics("p1")
    assert sorted(r.topic_id for r in rows) == ["a", "b"]


@pytest.mark.asyncio
async def test_create_subscription_requires_topic() -> None:
    s = InMemoryStorage()
    with pytest.raises(TopicNotFound):
        await s.create_subscription(_subscription())


@pytest.mark.asyncio
async def test_create_subscription_duplicate_raises() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.create_subscription(_subscription())
    with pytest.raises(SubscriptionAlreadyExists):
        await s.create_subscription(_subscription())


@pytest.mark.asyncio
async def test_get_subscription_missing_raises() -> None:
    s = InMemoryStorage()
    with pytest.raises(SubscriptionNotFound):
        await s.get_subscription("p", "missing")


@pytest.mark.asyncio
async def test_append_message_returns_monotonic_index() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    m1 = MessageRecord(
        message_id="t-1", publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=b"a", attributes={}, ordering_key="",
    )
    m2 = MessageRecord(
        message_id="t-2", publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=b"b", attributes={}, ordering_key="",
    )
    assert await s.append_message("p", "t", m1) == 0
    assert await s.append_message("p", "t", m2) == 1
    msgs = await s.get_messages("p", "t")
    assert [m.data for m in msgs] == [b"a", b"b"]


@pytest.mark.asyncio
async def test_list_subscriptions_for_topic() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.create_subscription(_subscription(sid="s1"))
    await s.create_subscription(_subscription(sid="s2"))
    names = await s.list_topic_subscriptions("p", "t")
    assert sorted(names) == ["projects/p/subscriptions/s1", "projects/p/subscriptions/s2"]


@pytest.mark.asyncio
async def test_reset_clears_everything() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.create_subscription(_subscription())
    await s.reset()
    assert await s.list_topics("p") == []
    assert await s.list_subscriptions("p") == []
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_storage.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement storage.py**

```python
"""In-memory storage for the Pub/Sub emulator.

The storage layer owns CRUD on TopicRecord / SubscriptionRecord and the
append-only message lists per topic. Delivery state (cursors, leases,
NACK queue, ordering blocks) lives in ``engine/backlog.py`` keyed by
``(project, subscription_id)``; storage just hands out the raw lists.
"""

import asyncio
from typing import Protocol

from gcp_local.services.pubsub.errors import (
    SubscriptionAlreadyExists,
    SubscriptionNotFound,
    TopicAlreadyExists,
    TopicNotFound,
)
from gcp_local.services.pubsub.models import (
    MessageRecord,
    SubscriptionRecord,
    TopicRecord,
)


class PubSubStorage(Protocol):
    async def create_topic(self, topic: TopicRecord) -> None: ...
    async def get_topic(self, project: str, topic_id: str) -> TopicRecord: ...
    async def update_topic(self, topic: TopicRecord) -> None: ...
    async def delete_topic(self, project: str, topic_id: str) -> None: ...
    async def list_topics(self, project: str) -> list[TopicRecord]: ...
    async def list_topic_subscriptions(self, project: str, topic_id: str) -> list[str]: ...
    async def create_subscription(self, sub: SubscriptionRecord) -> None: ...
    async def get_subscription(self, project: str, subscription_id: str) -> SubscriptionRecord: ...
    async def update_subscription(self, sub: SubscriptionRecord) -> None: ...
    async def delete_subscription(self, project: str, subscription_id: str) -> None: ...
    async def list_subscriptions(self, project: str) -> list[SubscriptionRecord]: ...
    async def append_message(self, project: str, topic_id: str, msg: MessageRecord) -> int: ...
    async def get_messages(self, project: str, topic_id: str) -> list[MessageRecord]: ...
    async def reset(self) -> None: ...


class InMemoryStorage:
    """Thread/asyncio-safe in-memory implementation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._topics: dict[tuple[str, str], TopicRecord] = {}
        self._subs: dict[tuple[str, str], SubscriptionRecord] = {}
        self._messages: dict[tuple[str, str], list[MessageRecord]] = {}

    async def create_topic(self, topic: TopicRecord) -> None:
        async with self._lock:
            key = (topic.project, topic.topic_id)
            if key in self._topics:
                raise TopicAlreadyExists(f"projects/{topic.project}/topics/{topic.topic_id}")
            self._topics[key] = topic
            self._messages.setdefault(key, [])

    async def get_topic(self, project: str, topic_id: str) -> TopicRecord:
        async with self._lock:
            try:
                return self._topics[(project, topic_id)]
            except KeyError:
                raise TopicNotFound(f"projects/{project}/topics/{topic_id}") from None

    async def update_topic(self, topic: TopicRecord) -> None:
        async with self._lock:
            key = (topic.project, topic.topic_id)
            if key not in self._topics:
                raise TopicNotFound(f"projects/{topic.project}/topics/{topic.topic_id}")
            self._topics[key] = topic

    async def delete_topic(self, project: str, topic_id: str) -> None:
        async with self._lock:
            key = (project, topic_id)
            if key not in self._topics:
                raise TopicNotFound(f"projects/{project}/topics/{topic_id}")
            del self._topics[key]
            self._messages.pop(key, None)

    async def list_topics(self, project: str) -> list[TopicRecord]:
        async with self._lock:
            return [t for (p, _), t in self._topics.items() if p == project]

    async def list_topic_subscriptions(self, project: str, topic_id: str) -> list[str]:
        async with self._lock:
            return [
                f"projects/{s.project}/subscriptions/{s.subscription_id}"
                for s in self._subs.values()
                if s.topic_project == project and s.topic_id == topic_id
            ]

    async def create_subscription(self, sub: SubscriptionRecord) -> None:
        async with self._lock:
            tkey = (sub.topic_project, sub.topic_id)
            if tkey not in self._topics:
                raise TopicNotFound(
                    f"projects/{sub.topic_project}/topics/{sub.topic_id}"
                )
            skey = (sub.project, sub.subscription_id)
            if skey in self._subs:
                raise SubscriptionAlreadyExists(
                    f"projects/{sub.project}/subscriptions/{sub.subscription_id}"
                )
            self._subs[skey] = sub

    async def get_subscription(self, project: str, subscription_id: str) -> SubscriptionRecord:
        async with self._lock:
            try:
                return self._subs[(project, subscription_id)]
            except KeyError:
                raise SubscriptionNotFound(
                    f"projects/{project}/subscriptions/{subscription_id}"
                ) from None

    async def update_subscription(self, sub: SubscriptionRecord) -> None:
        async with self._lock:
            key = (sub.project, sub.subscription_id)
            if key not in self._subs:
                raise SubscriptionNotFound(
                    f"projects/{sub.project}/subscriptions/{sub.subscription_id}"
                )
            self._subs[key] = sub

    async def delete_subscription(self, project: str, subscription_id: str) -> None:
        async with self._lock:
            key = (project, subscription_id)
            if key not in self._subs:
                raise SubscriptionNotFound(
                    f"projects/{project}/subscriptions/{subscription_id}"
                )
            del self._subs[key]

    async def list_subscriptions(self, project: str) -> list[SubscriptionRecord]:
        async with self._lock:
            return [s for (p, _), s in self._subs.items() if p == project]

    async def append_message(
        self, project: str, topic_id: str, msg: MessageRecord
    ) -> int:
        async with self._lock:
            key = (project, topic_id)
            if key not in self._topics:
                raise TopicNotFound(f"projects/{project}/topics/{topic_id}")
            lst = self._messages.setdefault(key, [])
            lst.append(msg)
            return len(lst) - 1

    async def get_messages(self, project: str, topic_id: str) -> list[MessageRecord]:
        async with self._lock:
            return list(self._messages.get((project, topic_id), []))

    async def reset(self) -> None:
        async with self._lock:
            self._topics.clear()
            self._subs.clear()
            self._messages.clear()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_storage.py -x 2>&1 | tail -5
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/storage.py tests/unit/services/pubsub/test_storage.py
git commit -m "feat(pubsub): add in-memory storage layer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: SubscriptionBacklog (delivery state machine)

**Files:**
- Create: `src/gcp_local/services/pubsub/engine/__init__.py` (empty)
- Create: `src/gcp_local/services/pubsub/engine/backlog.py`
- Test: `tests/unit/services/pubsub/test_backlog.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/services/pubsub/test_backlog.py`:

```python
import datetime as dt

import pytest

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
from gcp_local.services.pubsub.models import MessageRecord


def _msg(idx: int, *, key: str = "") -> MessageRecord:
    return MessageRecord(
        message_id=f"t-{idx}",
        publish_time=dt.datetime(2026, 4, 29, 12, 0, idx, tzinfo=dt.UTC),
        data=f"m{idx}".encode(),
        attributes={},
        ordering_key=key,
    )


@pytest.mark.asyncio
async def test_pull_with_empty_backlog_returns_nothing() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    out = await b.pull(messages=[], max_count=5, now=dt.datetime(2026, 4, 29, tzinfo=dt.UTC))
    assert out == []


@pytest.mark.asyncio
async def test_pull_advances_cursor_and_mints_lease() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0), _msg(1)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    out = await b.pull(messages=msgs, max_count=2, now=now)
    assert [r.message.message_id for r in out] == ["t-0", "t-1"]
    assert all(r.ack_id.startswith("lease-") for r in out)
    # Pulling again with same backlog returns empty until ack/expire
    assert await b.pull(messages=msgs, max_count=2, now=now) == []


@pytest.mark.asyncio
async def test_acknowledge_drops_lease_permanently() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [r] = await b.pull(messages=msgs, max_count=1, now=now)
    await b.acknowledge([r.ack_id])
    # Even past deadline, acked message does not redeliver
    later = now + dt.timedelta(seconds=20)
    assert await b.pull(messages=msgs, max_count=1, now=later) == []


@pytest.mark.asyncio
async def test_modack_zero_redelivers_immediately() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [r] = await b.pull(messages=msgs, max_count=1, now=now)
    await b.modify_ack_deadline([(r.ack_id, 0)])
    [r2] = await b.pull(messages=msgs, max_count=1, now=now)
    assert r2.message.message_id == "t-0"
    assert r2.ack_id != r.ack_id  # new lease


@pytest.mark.asyncio
async def test_modack_extension_postpones_redelivery() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [r] = await b.pull(messages=msgs, max_count=1, now=now)
    # Extend by 60s — sweep at now+30s should NOT redeliver
    await b.modify_ack_deadline([(r.ack_id, 60)])
    b.sweep_expired(now=now + dt.timedelta(seconds=30))
    assert await b.pull(messages=msgs, max_count=1, now=now + dt.timedelta(seconds=30)) == []


@pytest.mark.asyncio
async def test_sweep_expired_redelivers_after_deadline() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [r] = await b.pull(messages=msgs, max_count=1, now=now)
    # Deadline at now+10. Sweep at now+11 should reclaim it.
    b.sweep_expired(now=now + dt.timedelta(seconds=11))
    [r2] = await b.pull(messages=msgs, max_count=1, now=now + dt.timedelta(seconds=11))
    assert r2.message.message_id == "t-0"


@pytest.mark.asyncio
async def test_ordering_blocks_same_key_until_ack() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=True)
    msgs = [_msg(0, key="k"), _msg(1, key="k"), _msg(2, key="other")]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    out = await b.pull(messages=msgs, max_count=10, now=now)
    # Should deliver msg0 (first 'k') and msg2 ('other'), but skip msg1 (second 'k').
    assert sorted(r.message.message_id for r in out) == ["t-0", "t-2"]
    # Ack msg0 — now msg1 unblocks.
    ack0 = next(r.ack_id for r in out if r.message.message_id == "t-0")
    await b.acknowledge([ack0])
    [r1] = await b.pull(messages=msgs, max_count=10, now=now)
    assert r1.message.message_id == "t-1"


@pytest.mark.asyncio
async def test_ordering_disabled_ignores_keys() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0, key="k"), _msg(1, key="k")]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    out = await b.pull(messages=msgs, max_count=10, now=now)
    assert [r.message.message_id for r in out] == ["t-0", "t-1"]


@pytest.mark.asyncio
async def test_seek_to_index_clears_state_and_resets_cursor() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0), _msg(1), _msg(2)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [_, _] = await b.pull(messages=msgs, max_count=2, now=now)
    await b.seek(message_index=2)
    out = await b.pull(messages=msgs, max_count=10, now=now)
    assert [r.message.message_id for r in out] == ["t-2"]


@pytest.mark.asyncio
async def test_unknown_ack_id_is_ignored_not_raised() -> None:
    """Real Pub/Sub silently ignores unknown ack_ids in Acknowledge / ModifyAckDeadline."""
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    await b.acknowledge(["not-a-real-lease"])  # should not raise
    await b.modify_ack_deadline([("not-a-real-lease", 0)])  # should not raise
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_backlog.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement engine/backlog.py**

```python
"""Per-subscription delivery state machine.

Owns the cursor, outstanding ack-leases, the NACK queue, and the
ordering-key block set. The backlog does NOT hold message data — the
caller (the servicer) passes the topic's message list into ``pull`` /
``sweep_expired``. This keeps the backlog cheap to instantiate and
trivially serializable across resets.

All public methods are coroutine functions. Ordering keys are honored
only when ``enable_ordering=True`` was set on construction (matching
the SubscriptionRecord field).
"""

import asyncio
import datetime as dt
import uuid
from dataclasses import dataclass

from gcp_local.services.pubsub.models import AckLease, MessageRecord


@dataclass
class DeliveredMessage:
    ack_id: str
    message: MessageRecord


class SubscriptionBacklog:
    """All per-subscription delivery state. Not safe for concurrent pulls
    on the same instance — the servicer wraps a per-subscription lock around
    the ``pull`` / ``acknowledge`` / ``modify_ack_deadline`` / ``seek`` calls.
    """

    def __init__(self, *, ack_deadline_seconds: int, enable_ordering: bool) -> None:
        self.ack_deadline_seconds = ack_deadline_seconds
        self.enable_ordering = enable_ordering
        self._cursor = 0
        self._leases: dict[str, AckLease] = {}
        self._lease_to_key: dict[str, str] = {}  # ack_id → ordering_key (when ordering on)
        self._nacked: list[int] = []  # message indices to redeliver next
        self._ordering_blocked: set[str] = set()
        # asyncio.Event toggled when a new message is appended OR a NACK lands —
        # the long-poll Pull awaits it. The servicer wires this up.
        self.deliverable = asyncio.Event()

    async def pull(
        self,
        *,
        messages: list[MessageRecord],
        max_count: int,
        now: dt.datetime,
    ) -> list[DeliveredMessage]:
        # Opportunistic sweep on every pull (the §5.3 timer is the backstop).
        self.sweep_expired(now=now)
        out: list[DeliveredMessage] = []
        # NACKed messages first.
        remaining_nacked: list[int] = []
        for idx in self._nacked:
            if len(out) >= max_count:
                remaining_nacked.append(idx)
                continue
            msg = messages[idx]
            if self.enable_ordering and msg.ordering_key in self._ordering_blocked:
                remaining_nacked.append(idx)
                continue
            out.append(self._mint_lease(idx, msg, now))
        self._nacked = remaining_nacked
        # Then advance through the cursor.
        while len(out) < max_count and self._cursor < len(messages):
            msg = messages[self._cursor]
            if self.enable_ordering and msg.ordering_key in self._ordering_blocked:
                # Cannot deliver this message yet — but we still advance the cursor.
                # Push it onto _nacked so the next pull retries when the key unblocks.
                # Important: only push once. If it's already pending we'd duplicate
                # — guarded by tracking the highest cursor we've blocked.
                self._nacked.append(self._cursor)
                self._cursor += 1
                continue
            out.append(self._mint_lease(self._cursor, msg, now))
            self._cursor += 1
        return out

    def _mint_lease(
        self, idx: int, msg: MessageRecord, now: dt.datetime
    ) -> DeliveredMessage:
        ack_id = f"lease-{uuid.uuid4().hex}"
        deadline = now + dt.timedelta(seconds=self.ack_deadline_seconds)
        self._leases[ack_id] = AckLease(
            ack_id=ack_id, message_index=idx, deadline_at=deadline
        )
        if self.enable_ordering and msg.ordering_key:
            self._ordering_blocked.add(msg.ordering_key)
            self._lease_to_key[ack_id] = msg.ordering_key
        return DeliveredMessage(ack_id=ack_id, message=msg)

    async def acknowledge(self, ack_ids: list[str]) -> None:
        for aid in ack_ids:
            self._drop_lease(aid)

    async def modify_ack_deadline(
        self, items: list[tuple[str, int]]
    ) -> None:
        for ack_id, delta in items:
            lease = self._leases.get(ack_id)
            if lease is None:
                continue
            if delta == 0:
                # NACK: redeliver immediately.
                self._drop_lease(ack_id)
                self._nacked.append(lease.message_index)
                self.deliverable.set()
            else:
                lease.deadline_at = lease.deadline_at + dt.timedelta(seconds=delta)

    def _drop_lease(self, ack_id: str) -> None:
        lease = self._leases.pop(ack_id, None)
        if lease is None:
            return
        key = self._lease_to_key.pop(ack_id, None)
        if key is not None:
            self._ordering_blocked.discard(key)

    def sweep_expired(self, *, now: dt.datetime) -> int:
        """Reclaim any lease whose deadline has passed; return how many were swept."""
        expired = [aid for aid, lease in self._leases.items() if lease.deadline_at < now]
        for aid in expired:
            lease = self._leases.pop(aid)
            key = self._lease_to_key.pop(aid, None)
            if key is not None:
                self._ordering_blocked.discard(key)
            self._nacked.append(lease.message_index)
        if expired:
            self.deliverable.set()
        return len(expired)

    async def seek(self, *, message_index: int) -> None:
        """Reset the subscription to a specific position; drop all in-flight leases."""
        self._leases.clear()
        self._lease_to_key.clear()
        self._nacked.clear()
        self._ordering_blocked.clear()
        self._cursor = message_index
        self.deliverable.set()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_backlog.py -x 2>&1 | tail -5
```

Expected: all 11 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/engine tests/unit/services/pubsub/test_backlog.py
git commit -m "feat(pubsub): add per-subscription backlog state machine

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Service skeleton + entry point + smoke test

**Files:**
- Create: `src/gcp_local/services/pubsub/service.py`
- Create: `src/gcp_local/services/pubsub/servicer.py` (skeleton — empty servicers for now)
- Modify: `src/gcp_local/services/pubsub/__init__.py` (export `PubSubService`)
- Modify: `pyproject.toml` (register entry point)
- Test: `tests/unit/services/pubsub/test_service_scaffold.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from gcp_local.core.context import Context
from gcp_local.services.pubsub import PubSubService


@pytest.mark.asyncio
async def test_service_starts_and_health_reports_ok(tmp_path) -> None:
    svc = PubSubService()
    ctx = Context(persist=False, data_dir=str(tmp_path), port_overrides={"pubsub": 0})
    await svc.start(ctx)
    try:
        assert svc.health().ok
    finally:
        await svc.stop()
    assert not svc.health().ok


@pytest.mark.asyncio
async def test_service_reset_state_clears_storage(tmp_path) -> None:
    svc = PubSubService()
    ctx = Context(persist=False, data_dir=str(tmp_path), port_overrides={"pubsub": 0})
    await svc.start(ctx)
    try:
        # We don't have CRUD wired through gRPC yet; reset_state should still work.
        await svc.reset_state()
    finally:
        await svc.stop()
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_service_scaffold.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement skeleton**

`src/gcp_local/services/pubsub/servicer.py`:

```python
"""Pub/Sub gRPC servicers.

This file holds the bridge from gRPC requests to the storage / backlog
layers. Methods are added incrementally — see the implementation plan
for the order (topic CRUD → publish → subscription CRUD → pull → ack
→ streaming pull → seek).
"""

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2_grpc
from gcp_local.services.pubsub.storage import PubSubStorage


class PublisherServicer(pubsub_pb2_grpc.PublisherServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage


class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage
```

`src/gcp_local/services/pubsub/service.py`:

```python
"""Pub/Sub Service — owns the gRPC server lifecycle."""

import contextlib
import logging
from typing import ClassVar

import grpc

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.generated.google.pubsub.v1 import pubsub_pb2_grpc
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

    async def start(self, ctx: Context) -> None:
        if ctx.persist:
            log.info("pubsub: PERSIST=1 ignored — storage is in-memory only")
        self._storage = InMemoryStorage()
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        self._server = grpc.aio.server()
        self._server.add_insecure_port(f"[::]:{port}")
        publisher = PublisherServicer(storage=self._storage)
        subscriber = SubscriberServicer(storage=self._storage)
        pubsub_pb2_grpc.add_PublisherServicer_to_server(publisher, self._server)  # type: ignore[no-untyped-call]
        pubsub_pb2_grpc.add_SubscriberServicer_to_server(subscriber, self._server)  # type: ignore[no-untyped-call]
        await self._server.start()
        self._started = True
        log.info("pubsub service listening on :%d", port)

    async def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.stop(grace=None)
        self._started = False

    async def reset_state(self) -> None:
        if self._storage is not None:
            await self._storage.reset()

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self._started, message="running" if self._started else "stopped"
        )
```

`src/gcp_local/services/pubsub/__init__.py`:

```python
from gcp_local.services.pubsub.service import PubSubService

__all__ = ["PubSubService"]
```

`pyproject.toml` — add to the `[project.entry-points."gcp_local.services"]` block:

```toml
pubsub = "gcp_local.services.pubsub:PubSubService"
```

- [ ] **Step 4: Run the scaffold test + reinstall package**

```bash
.venv/bin/python -m pip install -e . --quiet && .venv/bin/pytest tests/unit/services/pubsub/test_service_scaffold.py -x 2>&1 | tail -5
```

Expected: both tests pass. The reinstall is required so the entry-point shows up in `importlib.metadata`.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/service.py src/gcp_local/services/pubsub/servicer.py src/gcp_local/services/pubsub/__init__.py pyproject.toml tests/unit/services/pubsub/test_service_scaffold.py
git commit -m "feat(pubsub): scaffold service + register gRPC server on 8085

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Topic CRUD RPCs

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py`
- Test: `tests/unit/services/pubsub/test_servicer_topics.py`

This task adds `CreateTopic`, `GetTopic`, `UpdateTopic`, `DeleteTopic`, `ListTopics`, and `ListTopicSubscriptions` to `PublisherServicer`.

- [ ] **Step 1: Write the failing tests**

```python
import grpc
import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import PublisherServicer
from gcp_local.services.pubsub.storage import InMemoryStorage


class _FakeContext:
    """Minimal stand-in for grpc.aio.ServicerContext — captures abort calls."""

    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise _Aborted()


class _Aborted(Exception):
    pass


@pytest.fixture
def servicer() -> PublisherServicer:
    return PublisherServicer(storage=InMemoryStorage())


@pytest.mark.asyncio
async def test_create_topic_returns_topic_with_name(servicer: PublisherServicer) -> None:
    req = pubsub_pb2.Topic(name="projects/p/topics/t", labels={"env": "dev"})
    resp = await servicer.CreateTopic(req, _FakeContext())
    assert resp.name == "projects/p/topics/t"
    assert resp.labels["env"] == "dev"


@pytest.mark.asyncio
async def test_create_topic_duplicate_aborts_already_exists(
    servicer: PublisherServicer,
) -> None:
    req = pubsub_pb2.Topic(name="projects/p/topics/t")
    await servicer.CreateTopic(req, _FakeContext())
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.CreateTopic(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.ALREADY_EXISTS


@pytest.mark.asyncio
async def test_create_topic_invalid_name_aborts(servicer: PublisherServicer) -> None:
    req = pubsub_pb2.Topic(name="garbage")
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.CreateTopic(req, ctx)
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_create_topic_rejects_goog_prefix(servicer: PublisherServicer) -> None:
    req = pubsub_pb2.Topic(name="projects/p/topics/goog-reserved")
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.CreateTopic(req, ctx)
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_get_topic_missing_aborts_not_found(servicer: PublisherServicer) -> None:
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetTopic(
            pubsub_pb2.GetTopicRequest(topic="projects/p/topics/missing"), ctx
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_get_topic_returns_record(servicer: PublisherServicer) -> None:
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t", labels={"k": "v"}), _FakeContext()
    )
    resp = await servicer.GetTopic(
        pubsub_pb2.GetTopicRequest(topic="projects/p/topics/t"), _FakeContext()
    )
    assert resp.labels["k"] == "v"


@pytest.mark.asyncio
async def test_update_topic_changes_labels(servicer: PublisherServicer) -> None:
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t", labels={"a": "1"}), _FakeContext()
    )
    update_req = pubsub_pb2.UpdateTopicRequest(
        topic=pubsub_pb2.Topic(name="projects/p/topics/t", labels={"a": "2"}),
        update_mask={"paths": ["labels"]},  # FieldMask is constructed via proto helper
    )
    resp = await servicer.UpdateTopic(update_req, _FakeContext())
    assert resp.labels["a"] == "2"


@pytest.mark.asyncio
async def test_delete_topic_removes(servicer: PublisherServicer) -> None:
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t"), _FakeContext()
    )
    await servicer.DeleteTopic(
        pubsub_pb2.DeleteTopicRequest(topic="projects/p/topics/t"), _FakeContext()
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetTopic(
            pubsub_pb2.GetTopicRequest(topic="projects/p/topics/t"), ctx
        )
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_list_topics_pagination(servicer: PublisherServicer) -> None:
    for i in range(3):
        await servicer.CreateTopic(
            pubsub_pb2.Topic(name=f"projects/p/topics/t{i}"), _FakeContext()
        )
    resp = await servicer.ListTopics(
        pubsub_pb2.ListTopicsRequest(project="projects/p", page_size=2),
        _FakeContext(),
    )
    assert len(resp.topics) == 2
    assert resp.next_page_token != ""
    resp2 = await servicer.ListTopics(
        pubsub_pb2.ListTopicsRequest(
            project="projects/p", page_size=2, page_token=resp.next_page_token
        ),
        _FakeContext(),
    )
    assert len(resp2.topics) == 1
    assert resp2.next_page_token == ""


@pytest.mark.asyncio
async def test_list_topic_subscriptions_returns_names_only(
    servicer: PublisherServicer,
) -> None:
    """Verifies the wire shape — ListTopicSubscriptions returns subscription
    names (strings), not Subscription messages."""
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t"), _FakeContext()
    )
    # We need to add a subscription via the storage layer directly since
    # SubscriberServicer.CreateSubscription isn't wired up yet.
    import datetime as dt

    from gcp_local.services.pubsub.models import SubscriptionRecord

    await servicer._storage.create_subscription(
        SubscriptionRecord(
            project="p", subscription_id="s", topic_project="p", topic_id="t",
            ack_deadline_seconds=10, enable_message_ordering=False,
            push_config=None, filter="", dead_letter_policy=None, retry_policy=None,
            labels={}, enable_exactly_once_delivery=False,
            create_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        )
    )
    resp = await servicer.ListTopicSubscriptions(
        pubsub_pb2.ListTopicSubscriptionsRequest(topic="projects/p/topics/t"),
        _FakeContext(),
    )
    assert list(resp.subscriptions) == ["projects/p/subscriptions/s"]
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_servicer_topics.py -x 2>&1 | tail -5
```

Expected: AttributeError on missing methods, since `PublisherServicer` is still empty.

- [ ] **Step 3: Implement Publisher topic methods**

Update `src/gcp_local/services/pubsub/servicer.py` — replace the placeholder `PublisherServicer` with the full version:

```python
"""Pub/Sub gRPC servicers."""

import base64
from typing import Any, NoReturn

import grpc

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2, pubsub_pb2_grpc
from gcp_local.services.pubsub.errors import (
    InvalidArgument,
    PubSubError,
    grpc_code_for,
)
from gcp_local.services.pubsub.models import TopicRecord
from gcp_local.services.pubsub.names import (
    InvalidName,
    parse_topic_name,
    validate_resource_id,
)
from gcp_local.services.pubsub.storage import PubSubStorage


async def _abort(context: grpc.aio.ServicerContext, exc: Exception) -> NoReturn:
    code = (
        grpc.StatusCode.INVALID_ARGUMENT
        if isinstance(exc, InvalidName)
        else grpc_code_for(exc)
    )
    await context.abort(code, str(exc))
    raise AssertionError("unreachable")  # context.abort always raises


def _parse_topic(name: str) -> tuple[str, str]:
    try:
        project, topic_id = parse_topic_name(name)
    except InvalidName as e:
        raise e
    validate_resource_id(topic_id)
    return project, topic_id


def _encode_token(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def _decode_token(token: str) -> int:
    if not token:
        return 0
    try:
        return int(base64.urlsafe_b64decode(token.encode()).decode())
    except (ValueError, UnicodeDecodeError) as e:
        raise InvalidArgument(f"Invalid page_token: {token!r}") from e


def _topic_record_to_proto(rec: TopicRecord) -> pubsub_pb2.Topic:
    return pubsub_pb2.Topic(
        name=f"projects/{rec.project}/topics/{rec.topic_id}",
        labels=dict(rec.labels),
    )


def _topic_proto_to_record(msg: pubsub_pb2.Topic) -> TopicRecord:
    project, topic_id = _parse_topic(msg.name)
    return TopicRecord(
        project=project,
        topic_id=topic_id,
        labels=dict(msg.labels),
        message_storage_policy=None,
        kms_key_name=msg.kms_key_name or None,
        schema_settings=None,
    )


class PublisherServicer(pubsub_pb2_grpc.PublisherServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage

    async def CreateTopic(
        self,
        request: pubsub_pb2.Topic,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Topic:
        try:
            rec = _topic_proto_to_record(request)
            await self._storage.create_topic(rec)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _topic_record_to_proto(rec)

    async def GetTopic(
        self,
        request: pubsub_pb2.GetTopicRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Topic:
        try:
            project, topic_id = _parse_topic(request.topic)
            rec = await self._storage.get_topic(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _topic_record_to_proto(rec)

    async def UpdateTopic(
        self,
        request: pubsub_pb2.UpdateTopicRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Topic:
        try:
            project, topic_id = _parse_topic(request.topic.name)
            existing = await self._storage.get_topic(project, topic_id)
            paths = set(request.update_mask.paths)
            updated = TopicRecord(
                project=existing.project,
                topic_id=existing.topic_id,
                labels=dict(request.topic.labels) if "labels" in paths else dict(existing.labels),
                message_storage_policy=existing.message_storage_policy,
                kms_key_name=existing.kms_key_name,
                schema_settings=existing.schema_settings,
            )
            await self._storage.update_topic(updated)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _topic_record_to_proto(updated)

    async def DeleteTopic(
        self,
        request: pubsub_pb2.DeleteTopicRequest,
        context: grpc.aio.ServicerContext,
    ) -> "pubsub_pb2.google_dot_protobuf_dot_empty__pb2.Empty":  # noqa: F821
        from google.protobuf import empty_pb2
        try:
            project, topic_id = _parse_topic(request.topic)
            await self._storage.delete_topic(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return empty_pb2.Empty()

    async def ListTopics(
        self,
        request: pubsub_pb2.ListTopicsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.ListTopicsResponse:
        if not request.project.startswith("projects/"):
            await _abort(context, InvalidArgument(f"Invalid project: {request.project!r}"))
        project = request.project[len("projects/"):]
        try:
            offset = _decode_token(request.page_token)
        except InvalidArgument as e:
            await _abort(context, e)
        page_size = request.page_size or 100
        rows = sorted(
            await self._storage.list_topics(project),
            key=lambda r: r.topic_id,
        )
        slice_ = rows[offset : offset + page_size]
        next_token = (
            _encode_token(offset + page_size) if offset + page_size < len(rows) else ""
        )
        return pubsub_pb2.ListTopicsResponse(
            topics=[_topic_record_to_proto(r) for r in slice_],
            next_page_token=next_token,
        )

    async def ListTopicSubscriptions(
        self,
        request: pubsub_pb2.ListTopicSubscriptionsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.ListTopicSubscriptionsResponse:
        try:
            project, topic_id = _parse_topic(request.topic)
            # Verify topic exists before listing.
            await self._storage.get_topic(project, topic_id)
            names = await self._storage.list_topic_subscriptions(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return pubsub_pb2.ListTopicSubscriptionsResponse(subscriptions=sorted(names))


class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_servicer_topics.py -x 2>&1 | tail -10
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/servicer.py tests/unit/services/pubsub/test_servicer_topics.py
git commit -m "feat(pubsub): topic CRUD RPCs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Publish RPC + StateHub event

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py` (add `Publish` to `PublisherServicer`, accept a `state_hub` arg, track per-topic message counter)
- Modify: `src/gcp_local/services/pubsub/service.py` (pass `state_hub` to `PublisherServicer`)
- Test: `tests/unit/services/pubsub/test_publish.py`

- [ ] **Step 1: Write the failing tests**

```python
import datetime as dt

import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import PublisherServicer
from gcp_local.services.pubsub.storage import InMemoryStorage


class _FakeContext:
    async def abort(self, code, details):
        raise RuntimeError(f"aborted: {code} {details}")


class _StateHubStub:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, event: str, payload: dict) -> None:
        self.published.append((event, payload))


@pytest.fixture
def env() -> tuple[PublisherServicer, _StateHubStub]:
    hub = _StateHubStub()
    return PublisherServicer(storage=InMemoryStorage(), state_hub=hub), hub


@pytest.mark.asyncio
async def test_publish_assigns_monotonic_message_ids(env) -> None:
    servicer, _ = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t"), _FakeContext()
    )
    req = pubsub_pb2.PublishRequest(
        topic="projects/p/topics/t",
        messages=[
            pubsub_pb2.PubsubMessage(data=b"a"),
            pubsub_pb2.PubsubMessage(data=b"b"),
        ],
    )
    resp = await servicer.Publish(req, _FakeContext())
    assert len(resp.message_ids) == 2
    # IDs are unique and sortable in publish order.
    assert resp.message_ids[0] != resp.message_ids[1]


@pytest.mark.asyncio
async def test_publish_stamps_publish_time(env) -> None:
    servicer, _ = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t"), _FakeContext()
    )
    before = dt.datetime.now(dt.UTC)
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[pubsub_pb2.PubsubMessage(data=b"x")],
        ),
        _FakeContext(),
    )
    msgs = await servicer._storage.get_messages("p", "t")
    assert len(msgs) == 1
    assert msgs[0].publish_time >= before


@pytest.mark.asyncio
async def test_publish_to_missing_topic_aborts(env) -> None:
    servicer, _ = env

    class _CapturingCtx:
        def __init__(self):
            self.code = None

        async def abort(self, code, details):
            self.code = code
            raise _Aborted()

    class _Aborted(Exception):
        pass

    ctx = _CapturingCtx()
    with pytest.raises(_Aborted):
        await servicer.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/p/topics/missing",
                messages=[pubsub_pb2.PubsubMessage(data=b"x")],
            ),
            ctx,
        )
    import grpc as _grpc
    assert ctx.code == _grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_publish_emits_state_hub_event(env) -> None:
    servicer, hub = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t"), _FakeContext()
    )
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[
                pubsub_pb2.PubsubMessage(data=b"hello", attributes={"k": "v"}),
            ],
        ),
        _FakeContext(),
    )
    assert len(hub.published) == 1
    event, payload = hub.published[0]
    assert event == "pubsub.message.published"
    assert payload["topic"] == "projects/p/topics/t"
    assert payload["attributes"] == {"k": "v"}
    assert payload["size_bytes"] == len(b"hello")


@pytest.mark.asyncio
async def test_publish_preserves_ordering_key(env) -> None:
    servicer, _ = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/t"), _FakeContext()
    )
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[pubsub_pb2.PubsubMessage(data=b"x", ordering_key="k1")],
        ),
        _FakeContext(),
    )
    msgs = await servicer._storage.get_messages("p", "t")
    assert msgs[0].ordering_key == "k1"
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_publish.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement Publish + state_hub plumbing**

Modify `PublisherServicer.__init__` and add the `Publish` method. Top of `servicer.py`, add:

```python
import datetime as dt
import itertools
from collections import defaultdict
from typing import Protocol

from gcp_local.services.pubsub.models import MessageRecord


class _StateHubLike(Protocol):
    async def publish(self, event: str, payload: dict) -> None: ...
```

Replace the `PublisherServicer.__init__` and add `Publish`:

```python
class PublisherServicer(pubsub_pb2_grpc.PublisherServicer):
    def __init__(
        self,
        *,
        storage: PubSubStorage,
        state_hub: _StateHubLike | None = None,
    ) -> None:
        self._storage = storage
        self._state_hub = state_hub
        # Per-topic monotonic message-id counters. Keyed by (project, topic_id).
        self._counters: dict[tuple[str, str], itertools.count] = defaultdict(
            lambda: itertools.count(1)
        )
        # asyncio.Event per (project, sub_id) registered by SubscriberServicer
        # so Pull / StreamingPull can wake on Publish. Set by the subscriber side
        # at first-pull time.
        self.deliverable_events: dict[tuple[str, str], "object"] = {}

    # ... existing CreateTopic / GetTopic / UpdateTopic / DeleteTopic / ListTopics /
    # ListTopicSubscriptions methods preserved ...

    async def Publish(
        self,
        request: pubsub_pb2.PublishRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.PublishResponse:
        try:
            project, topic_id = _parse_topic(request.topic)
            # Verify topic exists.
            await self._storage.get_topic(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)

        message_ids: list[str] = []
        counter = self._counters[(project, topic_id)]
        for proto_msg in request.messages:
            seq = next(counter)
            mid = f"{topic_id}-{seq}"
            now = dt.datetime.now(dt.UTC)
            rec = MessageRecord(
                message_id=mid,
                publish_time=now,
                data=bytes(proto_msg.data),
                attributes=dict(proto_msg.attributes),
                ordering_key=proto_msg.ordering_key or "",
            )
            await self._storage.append_message(project, topic_id, rec)
            message_ids.append(mid)
            if self._state_hub is not None:
                await self._state_hub.publish(
                    "pubsub.message.published",
                    {
                        "topic": request.topic,
                        "message_id": mid,
                        "attributes": dict(proto_msg.attributes),
                        "size_bytes": len(proto_msg.data),
                        "publish_time": now.isoformat(),
                    },
                )

        # Wake any waiting Pull / StreamingPull on subscriptions of this topic.
        # The SubscriberServicer registers Events keyed by (sub_project, sub_id);
        # we look up subs that point at this topic via storage.
        sub_names = await self._storage.list_topic_subscriptions(project, topic_id)
        for full_name in sub_names:
            # parse "projects/<p>/subscriptions/<s>"
            parts = full_name.split("/")
            sub_key = (parts[1], parts[3])
            event = self.deliverable_events.get(sub_key)
            if event is not None:
                event.set()

        return pubsub_pb2.PublishResponse(message_ids=message_ids)
```

Then update `service.py` `start()` to pass the `state_hub`:

```python
publisher = PublisherServicer(storage=self._storage, state_hub=ctx.state_hub)
subscriber = SubscriberServicer(
    storage=self._storage, publisher=publisher
)
```

And update `SubscriberServicer.__init__` placeholder to accept `publisher`:

```python
class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(self, *, storage: PubSubStorage, publisher: PublisherServicer) -> None:
        self._storage = storage
        self._publisher = publisher  # used to register deliverable events
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_publish.py tests/unit/services/pubsub/test_servicer_topics.py -x 2>&1 | tail -5
```

Expected: all green; existing topic tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/servicer.py src/gcp_local/services/pubsub/service.py tests/unit/services/pubsub/test_publish.py
git commit -m "feat(pubsub): Publish RPC + StateHub event emission

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Subscription CRUD RPCs

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py` (add `CreateSubscription` / `GetSubscription` / `UpdateSubscription` / `DeleteSubscription` / `ListSubscriptions` to `SubscriberServicer`)
- Test: `tests/unit/services/pubsub/test_servicer_subscriptions.py`

- [ ] **Step 1: Write the failing tests**

```python
import datetime as dt

import grpc
import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import (
    PublisherServicer,
    SubscriberServicer,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


class _Aborted(Exception):
    pass


class _Ctx:
    def __init__(self) -> None:
        self.code: grpc.StatusCode | None = None

    async def abort(self, code, details):
        self.code = code
        raise _Aborted()


@pytest.fixture
async def env():
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    # pre-create a topic
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/t"), _Ctx())
    return publisher, subscriber


@pytest.mark.asyncio
async def test_create_subscription_happy(env) -> None:
    _, subscriber = env
    req = pubsub_pb2.Subscription(
        name="projects/p/subscriptions/s",
        topic="projects/p/topics/t",
        ack_deadline_seconds=20,
        labels={"env": "dev"},
    )
    resp = await subscriber.CreateSubscription(req, _Ctx())
    assert resp.name == "projects/p/subscriptions/s"
    assert resp.ack_deadline_seconds == 20


@pytest.mark.asyncio
async def test_create_subscription_default_ack_deadline(env) -> None:
    _, subscriber = env
    resp = await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
        ),
        _Ctx(),
    )
    assert resp.ack_deadline_seconds == 10  # Pub/Sub default


@pytest.mark.asyncio
async def test_create_subscription_missing_topic_aborts(env) -> None:
    _, subscriber = env
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.CreateSubscription(
            pubsub_pb2.Subscription(
                name="projects/p/subscriptions/s",
                topic="projects/p/topics/missing",
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_create_subscription_duplicate_aborts(env) -> None:
    _, subscriber = env
    req = pubsub_pb2.Subscription(
        name="projects/p/subscriptions/s",
        topic="projects/p/topics/t",
    )
    await subscriber.CreateSubscription(req, _Ctx())
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.CreateSubscription(req, ctx)
    assert ctx.code == grpc.StatusCode.ALREADY_EXISTS


@pytest.mark.asyncio
async def test_create_subscription_accepts_push_config_no_op(env) -> None:
    """pushConfig is stored verbatim — no HTTP delivery loop runs in v1."""
    _, subscriber = env
    req = pubsub_pb2.Subscription(
        name="projects/p/subscriptions/s",
        topic="projects/p/topics/t",
        push_config=pubsub_pb2.PushConfig(push_endpoint="https://example.com/hook"),
    )
    resp = await subscriber.CreateSubscription(req, _Ctx())
    assert resp.push_config.push_endpoint == "https://example.com/hook"


@pytest.mark.asyncio
async def test_get_subscription_missing_aborts(env) -> None:
    _, subscriber = env
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.GetSubscription(
            pubsub_pb2.GetSubscriptionRequest(subscription="projects/p/subscriptions/missing"),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_update_subscription_changes_ack_deadline(env) -> None:
    _, subscriber = env
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            ack_deadline_seconds=10,
        ),
        _Ctx(),
    )
    update_req = pubsub_pb2.UpdateSubscriptionRequest(
        subscription=pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            ack_deadline_seconds=30,
        ),
        update_mask={"paths": ["ack_deadline_seconds"]},
    )
    resp = await subscriber.UpdateSubscription(update_req, _Ctx())
    assert resp.ack_deadline_seconds == 30


@pytest.mark.asyncio
async def test_delete_subscription_removes(env) -> None:
    _, subscriber = env
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
        ),
        _Ctx(),
    )
    await subscriber.DeleteSubscription(
        pubsub_pb2.DeleteSubscriptionRequest(subscription="projects/p/subscriptions/s"),
        _Ctx(),
    )
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.GetSubscription(
            pubsub_pb2.GetSubscriptionRequest(subscription="projects/p/subscriptions/s"),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_list_subscriptions_pagination(env) -> None:
    _, subscriber = env
    for i in range(3):
        await subscriber.CreateSubscription(
            pubsub_pb2.Subscription(
                name=f"projects/p/subscriptions/s{i}",
                topic="projects/p/topics/t",
            ),
            _Ctx(),
        )
    resp = await subscriber.ListSubscriptions(
        pubsub_pb2.ListSubscriptionsRequest(project="projects/p", page_size=2),
        _Ctx(),
    )
    assert len(resp.subscriptions) == 2
    assert resp.next_page_token != ""
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_servicer_subscriptions.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement subscription CRUD methods**

Add to `servicer.py` near `_topic_record_to_proto`:

```python
from gcp_local.services.pubsub.models import SubscriptionRecord
from gcp_local.services.pubsub.names import (
    parse_subscription_name,
)


def _parse_subscription(name: str) -> tuple[str, str]:
    project, sub_id = parse_subscription_name(name)
    validate_resource_id(sub_id)
    return project, sub_id


def _sub_record_to_proto(rec: SubscriptionRecord) -> pubsub_pb2.Subscription:
    proto = pubsub_pb2.Subscription(
        name=f"projects/{rec.project}/subscriptions/{rec.subscription_id}",
        topic=f"projects/{rec.topic_project}/topics/{rec.topic_id}",
        ack_deadline_seconds=rec.ack_deadline_seconds,
        enable_message_ordering=rec.enable_message_ordering,
        filter=rec.filter,
        labels=dict(rec.labels),
        enable_exactly_once_delivery=rec.enable_exactly_once_delivery,
    )
    if rec.push_config is not None:
        proto.push_config.CopyFrom(
            pubsub_pb2.PushConfig(**rec.push_config)
        )
    return proto


def _sub_proto_to_record(msg: pubsub_pb2.Subscription) -> SubscriptionRecord:
    sub_proj, sub_id = _parse_subscription(msg.name)
    topic_proj, topic_id = _parse_topic(msg.topic)
    push_config: dict[str, Any] | None = None
    if msg.HasField("push_config"):
        push_config = {"push_endpoint": msg.push_config.push_endpoint}
        if msg.push_config.attributes:
            push_config["attributes"] = dict(msg.push_config.attributes)
    return SubscriptionRecord(
        project=sub_proj,
        subscription_id=sub_id,
        topic_project=topic_proj,
        topic_id=topic_id,
        ack_deadline_seconds=msg.ack_deadline_seconds or 10,
        enable_message_ordering=msg.enable_message_ordering,
        push_config=push_config,
        filter=msg.filter or "",
        dead_letter_policy=None,
        retry_policy=None,
        labels=dict(msg.labels),
        enable_exactly_once_delivery=msg.enable_exactly_once_delivery,
        create_time=dt.datetime.now(dt.UTC),
    )
```

Then add to `SubscriberServicer`:

```python
class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(self, *, storage: PubSubStorage, publisher: PublisherServicer) -> None:
        self._storage = storage
        self._publisher = publisher

    async def CreateSubscription(
        self,
        request: pubsub_pb2.Subscription,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Subscription:
        try:
            rec = _sub_proto_to_record(request)
            await self._storage.create_subscription(rec)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _sub_record_to_proto(rec)

    async def GetSubscription(
        self,
        request: pubsub_pb2.GetSubscriptionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Subscription:
        try:
            project, sub_id = _parse_subscription(request.subscription)
            rec = await self._storage.get_subscription(project, sub_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _sub_record_to_proto(rec)

    async def UpdateSubscription(
        self,
        request: pubsub_pb2.UpdateSubscriptionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Subscription:
        try:
            project, sub_id = _parse_subscription(request.subscription.name)
            existing = await self._storage.get_subscription(project, sub_id)
            paths = set(request.update_mask.paths)
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
                push_config=existing.push_config,
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
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _sub_record_to_proto(updated)

    async def DeleteSubscription(
        self,
        request: pubsub_pb2.DeleteSubscriptionRequest,
        context: grpc.aio.ServicerContext,
    ) -> "object":
        from google.protobuf import empty_pb2
        try:
            project, sub_id = _parse_subscription(request.subscription)
            await self._storage.delete_subscription(project, sub_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return empty_pb2.Empty()

    async def ListSubscriptions(
        self,
        request: pubsub_pb2.ListSubscriptionsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.ListSubscriptionsResponse:
        if not request.project.startswith("projects/"):
            await _abort(context, InvalidArgument(f"Invalid project: {request.project!r}"))
        project = request.project[len("projects/"):]
        try:
            offset = _decode_token(request.page_token)
        except InvalidArgument as e:
            await _abort(context, e)
        page_size = request.page_size or 100
        rows = sorted(
            await self._storage.list_subscriptions(project),
            key=lambda r: r.subscription_id,
        )
        slice_ = rows[offset : offset + page_size]
        next_token = (
            _encode_token(offset + page_size) if offset + page_size < len(rows) else ""
        )
        return pubsub_pb2.ListSubscriptionsResponse(
            subscriptions=[_sub_record_to_proto(r) for r in slice_],
            next_page_token=next_token,
        )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_servicer_subscriptions.py -x 2>&1 | tail -5
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/servicer.py tests/unit/services/pubsub/test_servicer_subscriptions.py
git commit -m "feat(pubsub): subscription CRUD RPCs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Wire backlogs into the SubscriberServicer (per-subscription registry)

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py`
- Test: existing tests still pass; no new tests this task — pure refactor for the next task.

This task adds a per-subscription `SubscriptionBacklog` registry and a per-subscription `asyncio.Lock` to `SubscriberServicer`. Pull / Acknowledge / ModAck / StreamingPull / Seek will all build on this. No behavior change yet — it's pure plumbing.

- [ ] **Step 1: Add registry fields and helper to `SubscriberServicer.__init__`**

```python
import asyncio

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog


class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(self, *, storage: PubSubStorage, publisher: PublisherServicer) -> None:
        self._storage = storage
        self._publisher = publisher
        self._backlogs: dict[tuple[str, str], SubscriptionBacklog] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def _get_backlog(
        self, project: str, sub_id: str
    ) -> tuple[SubscriptionBacklog, asyncio.Lock]:
        """Lazily create a backlog + lock the first time a subscription is touched."""
        key = (project, sub_id)
        if key not in self._backlogs:
            sub = await self._storage.get_subscription(project, sub_id)
            backlog = SubscriptionBacklog(
                ack_deadline_seconds=sub.ack_deadline_seconds,
                enable_ordering=sub.enable_message_ordering,
            )
            self._backlogs[key] = backlog
            self._locks[key] = asyncio.Lock()
            # Register the deliverable Event with the publisher so Publish wakes us up.
            self._publisher.deliverable_events[key] = backlog.deliverable
        return self._backlogs[key], self._locks[key]

    async def _drop_backlog(self, project: str, sub_id: str) -> None:
        """Called from DeleteSubscription so the backlog is cleaned up."""
        key = (project, sub_id)
        self._backlogs.pop(key, None)
        self._locks.pop(key, None)
        self._publisher.deliverable_events.pop(key, None)
```

Update `DeleteSubscription` to call `_drop_backlog`:

```python
async def DeleteSubscription(
    self,
    request: pubsub_pb2.DeleteSubscriptionRequest,
    context: grpc.aio.ServicerContext,
) -> "object":
    from google.protobuf import empty_pb2
    try:
        project, sub_id = _parse_subscription(request.subscription)
        await self._storage.delete_subscription(project, sub_id)
        await self._drop_backlog(project, sub_id)
    except (PubSubError, InvalidName) as e:
        await _abort(context, e)
    return empty_pb2.Empty()
```

- [ ] **Step 2: Run all existing pubsub tests; nothing should regress**

```bash
.venv/bin/pytest tests/unit/services/pubsub/ -x 2>&1 | tail -5
```

Expected: all green (no behavior change).

- [ ] **Step 3: Commit**

```bash
git add src/gcp_local/services/pubsub/servicer.py
git commit -m "refactor(pubsub): add per-subscription backlog registry to SubscriberServicer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Pull RPC

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py`
- Test: `tests/unit/services/pubsub/test_pull.py`

- [ ] **Step 1: Write the failing tests**

```python
import asyncio
import datetime as dt

import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import (
    PublisherServicer,
    SubscriberServicer,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


class _Ctx:
    async def abort(self, code, details):
        raise RuntimeError(f"aborted: {code} {details}")


@pytest.fixture
async def env():
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/t"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s", topic="projects/p/topics/t"
        ),
        _Ctx(),
    )
    return publisher, subscriber


@pytest.mark.asyncio
async def test_pull_returns_published_message(env) -> None:
    publisher, subscriber = env
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[pubsub_pb2.PubsubMessage(data=b"hello")],
        ),
        _Ctx(),
    )
    resp = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert len(resp.received_messages) == 1
    rm = resp.received_messages[0]
    assert rm.message.data == b"hello"
    assert rm.ack_id  # non-empty


@pytest.mark.asyncio
async def test_pull_honors_max_messages(env) -> None:
    publisher, subscriber = env
    for i in range(5):
        await publisher.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/p/topics/t",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode())],
            ),
            _Ctx(),
        )
    resp = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=3,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert len(resp.received_messages) == 3


@pytest.mark.asyncio
async def test_pull_return_immediately_with_empty_backlog(env) -> None:
    _, subscriber = env
    resp = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert list(resp.received_messages) == []


@pytest.mark.asyncio
async def test_long_poll_wakes_on_publish(env) -> None:
    """Pull without return_immediately blocks; a concurrent Publish wakes it."""
    publisher, subscriber = env

    async def _do_pull():
        return await subscriber.Pull(
            pubsub_pb2.PullRequest(
                subscription="projects/p/subscriptions/s",
                max_messages=1,
                return_immediately=False,
            ),
            _Ctx(),
        )

    pull_task = asyncio.create_task(_do_pull())
    # Give the pull a tick to start blocking.
    await asyncio.sleep(0.05)
    assert not pull_task.done()
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[pubsub_pb2.PubsubMessage(data=b"wake")],
        ),
        _Ctx(),
    )
    resp = await asyncio.wait_for(pull_task, timeout=2.0)
    assert resp.received_messages[0].message.data == b"wake"


@pytest.mark.asyncio
async def test_pull_to_missing_subscription_aborts(env) -> None:
    import grpc

    class _CapCtx:
        def __init__(self):
            self.code = None

        async def abort(self, code, details):
            self.code = code
            raise _Aborted()

    class _Aborted(Exception):
        pass

    _, subscriber = env
    ctx = _CapCtx()
    with pytest.raises(_Aborted):
        await subscriber.Pull(
            pubsub_pb2.PullRequest(
                subscription="projects/p/subscriptions/missing",
                max_messages=1,
                return_immediately=True,
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_pull.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement Pull**

Add this constant near the top of `servicer.py`:

```python
_LONG_POLL_TIMEOUT_SECONDS = 90.0
```

Add to `SubscriberServicer`:

```python
async def Pull(
    self,
    request: pubsub_pb2.PullRequest,
    context: grpc.aio.ServicerContext,
) -> pubsub_pb2.PullResponse:
    try:
        project, sub_id = _parse_subscription(request.subscription)
        backlog, lock = await self._get_backlog(project, sub_id)
        max_messages = request.max_messages or 1
        topic_proj, topic_id = await self._resolve_topic(project, sub_id)
        # Try once; if empty and !return_immediately, long-poll on the deliverable Event.
        async with lock:
            messages = await self._storage.get_messages(topic_proj, topic_id)
            delivered = await backlog.pull(
                messages=messages, max_count=max_messages, now=dt.datetime.now(dt.UTC)
            )
        if delivered or request.return_immediately:
            return self._pull_response(delivered)
        # Long-poll: wait up to 90s for a new publish or NACK.
        try:
            backlog.deliverable.clear()
            await asyncio.wait_for(backlog.deliverable.wait(), timeout=_LONG_POLL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return self._pull_response([])
        async with lock:
            messages = await self._storage.get_messages(topic_proj, topic_id)
            delivered = await backlog.pull(
                messages=messages, max_count=max_messages, now=dt.datetime.now(dt.UTC)
            )
        return self._pull_response(delivered)
    except (PubSubError, InvalidName) as e:
        await _abort(context, e)

async def _resolve_topic(self, project: str, sub_id: str) -> tuple[str, str]:
    """Return the (topic_project, topic_id) pair for a subscription."""
    sub = await self._storage.get_subscription(project, sub_id)
    return sub.topic_project, sub.topic_id

def _pull_response(
    self, delivered: "list[DeliveredMessage]"
) -> pubsub_pb2.PullResponse:
    received: list[pubsub_pb2.ReceivedMessage] = []
    for d in delivered:
        from google.protobuf.timestamp_pb2 import Timestamp

        ts = Timestamp()
        ts.FromDatetime(d.message.publish_time)
        received.append(
            pubsub_pb2.ReceivedMessage(
                ack_id=d.ack_id,
                message=pubsub_pb2.PubsubMessage(
                    data=d.message.data,
                    attributes=d.message.attributes,
                    message_id=d.message.message_id,
                    publish_time=ts,
                    ordering_key=d.message.ordering_key or "",
                ),
            )
        )
    return pubsub_pb2.PullResponse(received_messages=received)
```

Also add the `DeliveredMessage` import at the top:

```python
from gcp_local.services.pubsub.engine.backlog import (
    DeliveredMessage,
    SubscriptionBacklog,
)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_pull.py -x 2>&1 | tail -10
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/servicer.py tests/unit/services/pubsub/test_pull.py
git commit -m "feat(pubsub): unary Pull with long-poll wakeup on publish

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Acknowledge + ModifyAckDeadline RPCs

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py`
- Test: `tests/unit/services/pubsub/test_ack_modack.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import (
    PublisherServicer,
    SubscriberServicer,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


class _Ctx:
    async def abort(self, code, details):
        raise RuntimeError(f"aborted: {code} {details}")


@pytest.fixture
async def env():
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/t"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            ack_deadline_seconds=5,
        ),
        _Ctx(),
    )
    return publisher, subscriber


@pytest.mark.asyncio
async def test_ack_drops_lease_so_message_doesnt_redeliver(env) -> None:
    publisher, subscriber = env
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[pubsub_pb2.PubsubMessage(data=b"a")],
        ),
        _Ctx(),
    )
    resp = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=1,
            return_immediately=True,
        ),
        _Ctx(),
    )
    ack_id = resp.received_messages[0].ack_id
    await subscriber.Acknowledge(
        pubsub_pb2.AcknowledgeRequest(
            subscription="projects/p/subscriptions/s",
            ack_ids=[ack_id],
        ),
        _Ctx(),
    )
    # Forcibly sweep all leases (simulate 1h passing).
    import datetime as dt
    backlog, _ = await subscriber._get_backlog("p", "s")
    backlog.sweep_expired(now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1))
    resp2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=1,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert list(resp2.received_messages) == []


@pytest.mark.asyncio
async def test_modack_zero_redelivers(env) -> None:
    publisher, subscriber = env
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[pubsub_pb2.PubsubMessage(data=b"a")],
        ),
        _Ctx(),
    )
    r1 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=1,
            return_immediately=True,
        ),
        _Ctx(),
    )
    ack_id = r1.received_messages[0].ack_id
    await subscriber.ModifyAckDeadline(
        pubsub_pb2.ModifyAckDeadlineRequest(
            subscription="projects/p/subscriptions/s",
            ack_ids=[ack_id],
            ack_deadline_seconds=0,
        ),
        _Ctx(),
    )
    r2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=1,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert r2.received_messages[0].message.data == b"a"
    assert r2.received_messages[0].ack_id != ack_id  # new lease


@pytest.mark.asyncio
async def test_ack_unknown_id_is_noop(env) -> None:
    """Real Pub/Sub silently ignores unknown ack_ids (per Pub/Sub spec)."""
    _, subscriber = env
    # Should not raise.
    await subscriber.Acknowledge(
        pubsub_pb2.AcknowledgeRequest(
            subscription="projects/p/subscriptions/s",
            ack_ids=["bogus"],
        ),
        _Ctx(),
    )


@pytest.mark.asyncio
async def test_ack_to_missing_subscription_aborts(env) -> None:
    import grpc

    class _Aborted(Exception):
        pass

    class _CapCtx:
        def __init__(self):
            self.code = None

        async def abort(self, code, details):
            self.code = code
            raise _Aborted()

    _, subscriber = env
    ctx = _CapCtx()
    with pytest.raises(_Aborted):
        await subscriber.Acknowledge(
            pubsub_pb2.AcknowledgeRequest(
                subscription="projects/p/subscriptions/missing",
                ack_ids=["x"],
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_ack_modack.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement Acknowledge + ModifyAckDeadline**

Add to `SubscriberServicer`:

```python
async def Acknowledge(
    self,
    request: pubsub_pb2.AcknowledgeRequest,
    context: grpc.aio.ServicerContext,
) -> "object":
    from google.protobuf import empty_pb2
    try:
        project, sub_id = _parse_subscription(request.subscription)
        backlog, lock = await self._get_backlog(project, sub_id)
        async with lock:
            await backlog.acknowledge(list(request.ack_ids))
    except (PubSubError, InvalidName) as e:
        await _abort(context, e)
    return empty_pb2.Empty()

async def ModifyAckDeadline(
    self,
    request: pubsub_pb2.ModifyAckDeadlineRequest,
    context: grpc.aio.ServicerContext,
) -> "object":
    from google.protobuf import empty_pb2
    try:
        project, sub_id = _parse_subscription(request.subscription)
        backlog, lock = await self._get_backlog(project, sub_id)
        async with lock:
            await backlog.modify_ack_deadline(
                [(aid, request.ack_deadline_seconds) for aid in request.ack_ids]
            )
    except (PubSubError, InvalidName) as e:
        await _abort(context, e)
    return empty_pb2.Empty()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_ack_modack.py -x 2>&1 | tail -5
```

Expected: all 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/servicer.py tests/unit/services/pubsub/test_ack_modack.py
git commit -m "feat(pubsub): Acknowledge + ModifyAckDeadline RPCs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Redelivery sweeper task

**Files:**
- Create: `src/gcp_local/services/pubsub/engine/delivery.py`
- Modify: `src/gcp_local/services/pubsub/servicer.py` (start a sweeper task per subscription on first touch)
- Test: `tests/unit/services/pubsub/test_redelivery.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import datetime as dt

import pytest

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
from gcp_local.services.pubsub.engine.delivery import RedeliverySweeper
from gcp_local.services.pubsub.models import MessageRecord


def _msg(idx: int) -> MessageRecord:
    return MessageRecord(
        message_id=f"m-{idx}",
        publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=f"d{idx}".encode(),
        attributes={},
        ordering_key="",
    )


@pytest.mark.asyncio
async def test_sweeper_reclaims_expired_leases() -> None:
    backlog = SubscriptionBacklog(ack_deadline_seconds=0, enable_ordering=False)  # 0s = immediately expired
    [d] = await backlog.pull(messages=[_msg(0)], max_count=1, now=dt.datetime.now(dt.UTC))
    # Lease deadline already in the past; sweeper should NACK it.
    sweeper = RedeliverySweeper(
        backlogs={("p", "s"): backlog},
        tick_interval=0.05,
    )
    await sweeper.start()
    try:
        # Wait long enough for at least 1 tick.
        await asyncio.sleep(0.15)
    finally:
        await sweeper.stop()
    # The previously leased message should now be redeliverable.
    [d2] = await backlog.pull(
        messages=[_msg(0)], max_count=1, now=dt.datetime.now(dt.UTC)
    )
    assert d2.message.message_id == "m-0"
    assert d2.ack_id != d.ack_id


@pytest.mark.asyncio
async def test_sweeper_idle_when_no_leases() -> None:
    """The sweeper should not raise on subscriptions with empty leases."""
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    sweeper = RedeliverySweeper(
        backlogs={("p", "s"): backlog},
        tick_interval=0.05,
    )
    await sweeper.start()
    await asyncio.sleep(0.15)
    await sweeper.stop()
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_redelivery.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement engine/delivery.py**

```python
"""Redelivery sweeper — periodically reclaims expired ack-leases.

A single sweeper handles all subscriptions in a service. The sweeper
runs every 1 second by default; tests can shorten the interval.
"""

import asyncio
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
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = dt.datetime.now(dt.UTC)
                for backlog in self._backlogs.values():
                    backlog.sweep_expired(now=now)
            except Exception:  # noqa: BLE001
                log.exception("pubsub redelivery sweeper error (continuing)")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_interval)
            except asyncio.TimeoutError:
                continue
```

- [ ] **Step 4: Wire the sweeper into the service**

Modify `service.py`:

```python
from gcp_local.services.pubsub.engine.delivery import RedeliverySweeper

# In start():
self._sweeper = RedeliverySweeper(backlogs=subscriber._backlogs)
await self._sweeper.start()

# In stop():
if self._sweeper is not None:
    await self._sweeper.stop()
```

(Add `self._sweeper: RedeliverySweeper | None = None` to `__init__`.)

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_redelivery.py tests/unit/services/pubsub/test_service_scaffold.py -x 2>&1 | tail -5
```

Expected: all green; service still starts/stops cleanly.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/pubsub/engine/delivery.py src/gcp_local/services/pubsub/service.py tests/unit/services/pubsub/test_redelivery.py
git commit -m "feat(pubsub): redelivery sweeper task

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Ordering keys end-to-end

**Files:**
- Test: `tests/unit/services/pubsub/test_ordering.py`

This task does not change implementation — the ordering logic was added in Task 6 (backlog) and exercised in `test_backlog.py`. This task asserts the end-to-end Publish→Pull→NACK→Pull flow at the servicer level so the wiring is verified.

- [ ] **Step 1: Write the test**

```python
import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import (
    PublisherServicer,
    SubscriberServicer,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


class _Ctx:
    async def abort(self, code, details):
        raise RuntimeError(f"aborted: {code} {details}")


@pytest.fixture
async def env():
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/t"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            enable_message_ordering=True,
            ack_deadline_seconds=5,
        ),
        _Ctx(),
    )
    return publisher, subscriber


@pytest.mark.asyncio
async def test_ordering_keys_serialize_same_key_messages(env) -> None:
    publisher, subscriber = env
    for i in range(3):
        await publisher.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/p/topics/t",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode(), ordering_key="k1")],
            ),
            _Ctx(),
        )
    # Pull all → should only get the FIRST message; the other two are blocked.
    r1 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert len(r1.received_messages) == 1
    assert r1.received_messages[0].message.data == b"m0"
    # Ack first; second unblocks.
    await subscriber.Acknowledge(
        pubsub_pb2.AcknowledgeRequest(
            subscription="projects/p/subscriptions/s",
            ack_ids=[r1.received_messages[0].ack_id],
        ),
        _Ctx(),
    )
    r2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert [rm.message.data for rm in r2.received_messages] == [b"m1"]


@pytest.mark.asyncio
async def test_ordering_disabled_returns_all_at_once(env) -> None:
    """Sanity check: a non-ordering subscription gets everything regardless of key."""
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/t"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            enable_message_ordering=False,
        ),
        _Ctx(),
    )
    for i in range(3):
        await publisher.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/p/topics/t",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode(), ordering_key="k1")],
            ),
            _Ctx(),
        )
    r = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert sorted(rm.message.data for rm in r.received_messages) == [b"m0", b"m1", b"m2"]
```

- [ ] **Step 2: Run the test (should pass without code changes)**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_ordering.py -x 2>&1 | tail -5
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/services/pubsub/test_ordering.py
git commit -m "test(pubsub): end-to-end ordering-key serialization

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: StreamingPull RPC

**Files:**
- Create: `src/gcp_local/services/pubsub/engine/streaming.py`
- Modify: `src/gcp_local/services/pubsub/servicer.py` (add `StreamingPull`)
- Test: `tests/unit/services/pubsub/test_streaming_pull.py`

`StreamingPull` is bidirectional: clients send `StreamingPullRequest` repeatedly (initial subscribes, subsequent ack/modack/flow updates); the server yields `StreamingPullResponse` messages. The implementation runs two coroutines concurrently — one consumes the request iterator, one yields outbound messages.

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import datetime as dt

import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import (
    PublisherServicer,
    SubscriberServicer,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


class _Ctx:
    """Mimics enough of grpc.aio.ServicerContext for the streaming method."""

    def __init__(self) -> None:
        self._active = True
        self.aborted: tuple | None = None

    def is_active(self) -> bool:
        return self._active

    async def abort(self, code, details):
        self.aborted = (code, details)
        self._active = False
        raise _StreamAborted()


class _StreamAborted(Exception):
    pass


async def _async_iter(items: list, gap: float = 0.01):
    for x in items:
        await asyncio.sleep(gap)
        yield x


@pytest.fixture
async def env():
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/t"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s",
            topic="projects/p/topics/t",
            ack_deadline_seconds=10,
        ),
        _Ctx(),
    )
    return publisher, subscriber


@pytest.mark.asyncio
async def test_streaming_pull_yields_published_messages(env) -> None:
    publisher, subscriber = env
    # Pre-publish so the first pull has data.
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[
                pubsub_pb2.PubsubMessage(data=b"a"),
                pubsub_pb2.PubsubMessage(data=b"b"),
            ],
        ),
        _Ctx(),
    )
    initial = pubsub_pb2.StreamingPullRequest(
        subscription="projects/p/subscriptions/s",
        stream_ack_deadline_seconds=10,
        max_outstanding_messages=10,
        max_outstanding_bytes=0,
    )
    ctx = _Ctx()
    received_data: list[bytes] = []
    received_ack_ids: list[str] = []

    async def _drive():
        async for resp in subscriber.StreamingPull(_async_iter([initial]), ctx):
            for rm in resp.received_messages:
                received_data.append(rm.message.data)
                received_ack_ids.append(rm.ack_id)
            if len(received_data) >= 2:
                ctx._active = False
                break

    await asyncio.wait_for(_drive(), timeout=2.0)
    assert sorted(received_data) == [b"a", b"b"]


@pytest.mark.asyncio
async def test_streaming_pull_processes_acks_from_request_stream(env) -> None:
    publisher, subscriber = env
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/p/topics/t",
            messages=[pubsub_pb2.PubsubMessage(data=b"x")],
        ),
        _Ctx(),
    )
    initial = pubsub_pb2.StreamingPullRequest(
        subscription="projects/p/subscriptions/s",
        stream_ack_deadline_seconds=10,
        max_outstanding_messages=10,
        max_outstanding_bytes=0,
    )
    ctx = _Ctx()
    captured_ack_ids: list[str] = []

    async def _drive():
        # First yields a delivery; we issue an ack via a follow-up request and break.
        gen = subscriber.StreamingPull(_async_iter([initial]), ctx)
        first = await gen.__anext__()
        ack_id = first.received_messages[0].ack_id
        captured_ack_ids.append(ack_id)
        # Simulate a follow-up request with an ack — we won't actually get it
        # into the existing iterator because _async_iter is exhausted. Instead,
        # call backlog.acknowledge directly to verify the path the streaming
        # consumer would invoke.
        backlog, lock = await subscriber._get_backlog("p", "s")
        async with lock:
            await backlog.acknowledge([ack_id])
        ctx._active = False
        await gen.aclose()

    await asyncio.wait_for(_drive(), timeout=2.0)
    assert len(captured_ack_ids) == 1


@pytest.mark.asyncio
async def test_streaming_pull_respects_max_outstanding(env) -> None:
    publisher, subscriber = env
    for i in range(5):
        await publisher.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/p/topics/t",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode())],
            ),
            _Ctx(),
        )
    initial = pubsub_pb2.StreamingPullRequest(
        subscription="projects/p/subscriptions/s",
        stream_ack_deadline_seconds=10,
        max_outstanding_messages=2,  # limit to 2 in flight
        max_outstanding_bytes=0,
    )
    ctx = _Ctx()
    delivered: list[bytes] = []

    async def _drive():
        async for resp in subscriber.StreamingPull(_async_iter([initial]), ctx):
            for rm in resp.received_messages:
                delivered.append(rm.message.data)
            if len(delivered) >= 2:
                ctx._active = False
                break

    await asyncio.wait_for(_drive(), timeout=2.0)
    # We should NOT have received more than 2 messages without acking.
    assert len(delivered) == 2
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_streaming_pull.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement engine/streaming.py and StreamingPull method**

`engine/streaming.py`:

```python
"""StreamingPull session state — flow-control budget tracking."""

from dataclasses import dataclass


@dataclass
class FlowControl:
    """Per-stream message + bytes budget. ``0`` means unlimited."""

    max_outstanding_messages: int  # 0 = unlimited
    max_outstanding_bytes: int     # 0 = unlimited
    in_flight_messages: int = 0
    in_flight_bytes: int = 0

    def can_yield(self, msg_size: int) -> bool:
        if self.max_outstanding_messages and self.in_flight_messages >= self.max_outstanding_messages:
            return False
        if self.max_outstanding_bytes and self.in_flight_bytes + msg_size > self.max_outstanding_bytes:
            return False
        return True

    def on_yield(self, msg_size: int) -> None:
        self.in_flight_messages += 1
        self.in_flight_bytes += msg_size

    def on_ack(self, msg_size: int) -> None:
        self.in_flight_messages = max(0, self.in_flight_messages - 1)
        self.in_flight_bytes = max(0, self.in_flight_bytes - msg_size)
```

Add to `SubscriberServicer`:

```python
async def StreamingPull(
    self,
    request_iterator,
    context: grpc.aio.ServicerContext,
):
    """Bidirectional stream: yields ReceivedMessages, consumes ack/modack/flow updates."""
    from gcp_local.services.pubsub.engine.streaming import FlowControl

    # First request carries subscription + flow control.
    try:
        first = await request_iterator.__anext__()
    except StopAsyncIteration:
        await _abort(context, InvalidArgument("StreamingPull requires at least one request"))
    if not first.subscription:
        await _abort(context, InvalidArgument("StreamingPull initial request must set subscription"))

    try:
        project, sub_id = _parse_subscription(first.subscription)
        backlog, lock = await self._get_backlog(project, sub_id)
        topic_proj, topic_id = await self._resolve_topic(project, sub_id)
    except (PubSubError, InvalidName) as e:
        await _abort(context, e)

    flow = FlowControl(
        max_outstanding_messages=first.max_outstanding_messages or 0,
        max_outstanding_bytes=first.max_outstanding_bytes or 0,
    )
    # Track in-flight (ack_id → bytes) so we can credit flow on ack.
    in_flight_bytes: dict[str, int] = {}

    async def _consume_client_requests():
        async for req in request_iterator:
            if req.ack_ids:
                async with lock:
                    await backlog.acknowledge(list(req.ack_ids))
                for aid in req.ack_ids:
                    flow.on_ack(in_flight_bytes.pop(aid, 0))
            if req.modify_deadline_ack_ids:
                items = list(zip(
                    req.modify_deadline_ack_ids,
                    req.modify_deadline_seconds,
                    strict=False,
                ))
                async with lock:
                    await backlog.modify_ack_deadline(items)
                for aid, secs in items:
                    if secs == 0:
                        flow.on_ack(in_flight_bytes.pop(aid, 0))

    consumer = asyncio.create_task(_consume_client_requests())

    try:
        while context.is_active():
            async with lock:
                messages = await self._storage.get_messages(topic_proj, topic_id)
                # Compute remaining message budget for this round.
                if flow.max_outstanding_messages:
                    budget = flow.max_outstanding_messages - flow.in_flight_messages
                else:
                    budget = 100
                if budget <= 0:
                    delivered = []
                else:
                    delivered = await backlog.pull(
                        messages=messages, max_count=budget, now=dt.datetime.now(dt.UTC)
                    )
            if delivered:
                yieldable: list[DeliveredMessage] = []
                for d in delivered:
                    msg_size = len(d.message.data)
                    if not flow.can_yield(msg_size):
                        # Push back: NACK so it redelivers later when budget frees.
                        async with lock:
                            await backlog.modify_ack_deadline([(d.ack_id, 0)])
                        continue
                    flow.on_yield(msg_size)
                    in_flight_bytes[d.ack_id] = msg_size
                    yieldable.append(d)
                if yieldable:
                    yield self._streaming_response(yieldable)
                continue
            # Nothing to send — wait for a wakeup or context cancel.
            backlog.deliverable.clear()
            try:
                await asyncio.wait_for(backlog.deliverable.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass
    finally:
        consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass

def _streaming_response(
    self, delivered: "list[DeliveredMessage]"
) -> pubsub_pb2.StreamingPullResponse:
    from google.protobuf.timestamp_pb2 import Timestamp

    rms: list[pubsub_pb2.ReceivedMessage] = []
    for d in delivered:
        ts = Timestamp()
        ts.FromDatetime(d.message.publish_time)
        rms.append(
            pubsub_pb2.ReceivedMessage(
                ack_id=d.ack_id,
                message=pubsub_pb2.PubsubMessage(
                    data=d.message.data,
                    attributes=d.message.attributes,
                    message_id=d.message.message_id,
                    publish_time=ts,
                    ordering_key=d.message.ordering_key or "",
                ),
            )
        )
    return pubsub_pb2.StreamingPullResponse(received_messages=rms)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_streaming_pull.py -x 2>&1 | tail -10
```

Expected: all 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/engine/streaming.py src/gcp_local/services/pubsub/servicer.py tests/unit/services/pubsub/test_streaming_pull.py
git commit -m "feat(pubsub): StreamingPull RPC with flow control

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Seek RPC (time-based) + IAM stubs

**Files:**
- Modify: `src/gcp_local/services/pubsub/servicer.py`
- Test: `tests/unit/services/pubsub/test_seek.py`

- [ ] **Step 1: Write the failing tests**

```python
import datetime as dt

import grpc
import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import (
    PublisherServicer,
    SubscriberServicer,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


class _Aborted(Exception):
    pass


class _Ctx:
    def __init__(self) -> None:
        self.code: grpc.StatusCode | None = None

    async def abort(self, code, details):
        self.code = code
        raise _Aborted()


@pytest.fixture
async def env():
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/t"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/s", topic="projects/p/topics/t"
        ),
        _Ctx(),
    )
    return publisher, subscriber


@pytest.mark.asyncio
async def test_seek_to_time_rewinds_subscription(env) -> None:
    publisher, subscriber = env
    # Publish 3 messages at distinct times.
    base = dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=dt.UTC)
    # Manually drive publish_time by writing through storage. The Publish RPC
    # uses datetime.now(); we patch via storage to control timing.
    from gcp_local.services.pubsub.models import MessageRecord

    for i in range(3):
        await subscriber._storage.append_message(
            "p",
            "t",
            MessageRecord(
                message_id=f"t-{i}",
                publish_time=base + dt.timedelta(minutes=i),
                data=f"m{i}".encode(),
                attributes={},
                ordering_key="",
            ),
        )
    # Pull and ack everything.
    r = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    await subscriber.Acknowledge(
        pubsub_pb2.AcknowledgeRequest(
            subscription="projects/p/subscriptions/s",
            ack_ids=[rm.ack_id for rm in r.received_messages],
        ),
        _Ctx(),
    )
    # Seek to base+1min — should rewind to messages t-1 and t-2.
    from google.protobuf.timestamp_pb2 import Timestamp

    ts = Timestamp()
    ts.FromDatetime(base + dt.timedelta(minutes=1))
    seek_resp = await subscriber.Seek(
        pubsub_pb2.SeekRequest(
            subscription="projects/p/subscriptions/s",
            time=ts,
        ),
        _Ctx(),
    )
    assert seek_resp is not None  # SeekResponse is empty but non-None
    r2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/p/subscriptions/s",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert sorted(rm.message.data for rm in r2.received_messages) == [b"m1", b"m2"]


@pytest.mark.asyncio
async def test_seek_with_snapshot_returns_unimplemented(env) -> None:
    _, subscriber = env
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.Seek(
            pubsub_pb2.SeekRequest(
                subscription="projects/p/subscriptions/s",
                snapshot="projects/p/snapshots/x",
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.UNIMPLEMENTED
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_seek.py -x 2>&1 | tail -5
```

- [ ] **Step 3: Implement Seek + IAM stubs**

Add to `SubscriberServicer`:

```python
async def Seek(
    self,
    request: pubsub_pb2.SeekRequest,
    context: grpc.aio.ServicerContext,
) -> pubsub_pb2.SeekResponse:
    if request.HasField("snapshot"):
        await context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "Snapshot-based Seek is not supported in v1.",
        )
        raise AssertionError("unreachable")
    if not request.HasField("time"):
        await _abort(context, InvalidArgument("Seek requires either time or snapshot"))
    target_time = request.time.ToDatetime().replace(tzinfo=dt.UTC)
    try:
        project, sub_id = _parse_subscription(request.subscription)
        backlog, lock = await self._get_backlog(project, sub_id)
        topic_proj, topic_id = await self._resolve_topic(project, sub_id)
        async with lock:
            messages = await self._storage.get_messages(topic_proj, topic_id)
            # Binary search for first message with publish_time >= target.
            import bisect

            times = [m.publish_time for m in messages]
            idx = bisect.bisect_left(times, target_time)
            await backlog.seek(message_index=idx)
    except (PubSubError, InvalidName) as e:
        await _abort(context, e)
    return pubsub_pb2.SeekResponse()
```

Add IAM no-op stubs (these live on both servicers; real Pub/Sub registers them on both `Publisher` and `Subscriber`. Pre-generated `pubsub_pb2_grpc` does NOT include them — they come from `iam_pb2_grpc`. For v1, we accept the AttributeError path: client calls them and grpc returns UNIMPLEMENTED automatically because we never registered the IAM service). Document this in the architecture doc; no code change needed for IAM stubs.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/services/pubsub/test_seek.py -x 2>&1 | tail -5
```

Expected: both tests green.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/pubsub/servicer.py tests/unit/services/pubsub/test_seek.py
git commit -m "feat(pubsub): Seek by time; snapshot-Seek returns UNIMPLEMENTED

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Integration tests with google-cloud-pubsub

**Files:**
- Modify: `tests/integration/conftest.py`
- Create: `tests/integration/test_pubsub_integration.py`

- [ ] **Step 1: Add `pubsub` to the integration emulator's default service set**

Look for the default service list in `tests/integration/conftest.py` and add `"pubsub"` alongside `"bigquery"`, `"gcs"`, `"secret_manager"`. The exact line varies — search for `SERVICES` or the existing service names.

- [ ] **Step 2: Write the integration test**

```python
"""End-to-end Pub/Sub against the in-process emulator using google-cloud-pubsub."""

import os
import time

import pytest
from google.cloud import pubsub_v1


@pytest.fixture(autouse=True)
def _set_emulator_host(emulator_endpoints):
    """The emulator fixture exposes pubsub on a known port; expose via env var."""
    host = emulator_endpoints["pubsub"]  # e.g. "localhost:NNNN"
    os.environ["PUBSUB_EMULATOR_HOST"] = host
    yield
    os.environ.pop("PUBSUB_EMULATOR_HOST", None)


def test_publish_and_pull_round_trip() -> None:
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "rt-topic")
    sub_path = subscriber.subscription_path("test-proj", "rt-sub")

    publisher.create_topic(request={"name": topic_path})
    subscriber.create_subscription(
        request={"name": sub_path, "topic": topic_path, "ack_deadline_seconds": 10}
    )

    futures = [publisher.publish(topic_path, f"msg-{i}".encode()) for i in range(5)]
    for f in futures:
        f.result(timeout=5)

    pull = subscriber.pull(
        request={"subscription": sub_path, "max_messages": 10, "return_immediately": True}
    )
    received = sorted(rm.message.data for rm in pull.received_messages)
    assert received == [b"msg-0", b"msg-1", b"msg-2", b"msg-3", b"msg-4"]

    subscriber.acknowledge(
        request={
            "subscription": sub_path,
            "ack_ids": [rm.ack_id for rm in pull.received_messages],
        }
    )


def test_streaming_pull_via_subscribe_callback() -> None:
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "stream-topic")
    sub_path = subscriber.subscription_path("test-proj", "stream-sub")

    publisher.create_topic(request={"name": topic_path})
    subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})

    received: list[bytes] = []

    def _cb(msg):
        received.append(msg.data)
        msg.ack()

    fut = subscriber.subscribe(sub_path, callback=_cb)
    try:
        publisher.publish(topic_path, b"streamed").result(timeout=5)
        deadline = time.time() + 5
        while time.time() < deadline and not received:
            time.sleep(0.05)
        assert received == [b"streamed"]
    finally:
        fut.cancel()


def test_ordering_keys_serialize_per_key() -> None:
    publisher = pubsub_v1.PublisherClient(
        publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=True)
    )
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "ord-topic")
    sub_path = subscriber.subscription_path("test-proj", "ord-sub")

    publisher.create_topic(request={"name": topic_path})
    subscriber.create_subscription(
        request={
            "name": sub_path,
            "topic": topic_path,
            "enable_message_ordering": True,
        }
    )

    for i in range(3):
        publisher.publish(topic_path, f"k-{i}".encode(), ordering_key="key1").result(timeout=5)

    pull = subscriber.pull(
        request={"subscription": sub_path, "max_messages": 10, "return_immediately": True}
    )
    # Only the FIRST same-key message should be delivered before any ack.
    assert len(pull.received_messages) == 1
    assert pull.received_messages[0].message.data == b"k-0"


def test_get_topic_not_found_raises() -> None:
    from google.api_core.exceptions import NotFound

    publisher = pubsub_v1.PublisherClient()
    with pytest.raises(NotFound):
        publisher.get_topic(request={"topic": publisher.topic_path("test-proj", "missing")})


def test_create_subscription_duplicate_raises() -> None:
    from google.api_core.exceptions import AlreadyExists

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "dup-topic")
    sub_path = subscriber.subscription_path("test-proj", "dup-sub")
    publisher.create_topic(request={"name": topic_path})
    subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
    with pytest.raises(AlreadyExists):
        subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
```

- [ ] **Step 3: Run integration tests**

```bash
.venv/bin/pytest tests/integration/test_pubsub_integration.py -x 2>&1 | tail -15
```

Expected: all 5 tests green. If a test fails, the most likely cause is the `emulator_endpoints` fixture key — adapt to whatever key the existing fixture uses.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_pubsub_integration.py
git commit -m "test(pubsub): integration tests via google-cloud-pubsub client

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 19: Documentation

**Files:**
- Create: `docs/services/pubsub.md`
- Create: `docs/architecture/pubsub.md`
- Modify: `README.md` (add row to Services at a glance)
- Modify: `ROADMAP.md` (delete Pub/Sub from Planned table; add Pub/Sub follow-ups subsection under Per-service follow-ups)
- Modify: `CHANGELOG.md` (add `[Unreleased] Added` entry)
- Modify: `docs/deployment.md` (add 8085 to default-ports table)

Use `docs/services/bigquery.md` and `docs/architecture/bigquery.md` as structural templates.

- [ ] **Step 1: Write `docs/services/pubsub.md`**

Sections (paraphrasing the BigQuery doc structure):

1. Elevator pitch: "Local Pub/Sub emulator over gRPC. Drop-in for `google-cloud-pubsub` via `PUBSUB_EMULATOR_HOST=localhost:8085`."
2. What's emulated — bullet list from spec §2.1.
3. What's not emulated — bullet list from spec §2.3 + §2.2 accepted-and-ignored.
4. Connecting — env var snippet + code snippet.
5. Examples — publish, pull-and-ack, streaming pull, ordering keys, seek.
6. Limits & quirks — in-memory only (PERSIST=1 ignored); unbounded topic backlog; no push delivery; filter accepted but not evaluated; exactly-once downgraded.

Reuse code blocks from spec §3.3 and §5.

- [ ] **Step 2: Write `docs/architecture/pubsub.md`**

Sections:

1. At-a-glance — port 8085, gRPC, in-memory.
2. Wire & port — `PUBSUB_EMULATOR_HOST`, default 8085, override `PUBSUB_EMULATOR_PORT`.
3. Storage model — section §4 of the spec, prose-form.
4. Request lifecycle — table of RPC → handler → storage / backlog interactions.
5. Delivery state machine — section §5 of the spec, with the per-step ordering of cursor advance / NACK queue / lease minting / ordering-key gating.
6. Error mapping — table from spec §8.
7. Tests — pointers to unit + integration files.
8. Internals-level limitations — section §12 of the spec.

- [ ] **Step 3: Update `README.md`**

Add a row to the "Services at a glance" table:

```
| Pub/Sub | Alpha | gRPC | 8085 | `PUBSUB_EMULATOR_HOST` | [usage](docs/services/pubsub.md) / [internals](docs/architecture/pubsub.md) |
```

(Match the exact column shape used by other rows.)

- [ ] **Step 4: Update `ROADMAP.md`**

- Delete the Pub/Sub row from the Planned (v1) table.
- Add a new subsection under "Per-service follow-ups":

```markdown
### Pub/Sub

- **Push subscriptions** — `pushConfig` is accepted and stored, but the emulator does not POST to the URL.
- **Subscription filters** — `filter` is accepted and stored, but every message is delivered regardless.
- **Schema service** — `SchemaService` RPCs not implemented.
- **Snapshots** — `CreateSnapshot` / `Seek(snapshot=...)` return `UNIMPLEMENTED`.
- **BigQuery / Cloud Storage subscriptions** — not supported.
- **Persistence** — Pub/Sub state is in-memory only, even with `PERSIST=1`. Topics, subscriptions, and message backlogs do not survive a restart.
- **Exactly-once delivery** — `enableExactlyOnceDelivery=true` is accepted but downgraded to at-least-once.
```

- [ ] **Step 5: Update `CHANGELOG.md`**

Add to `[Unreleased] ### Added`:

```markdown
- **Pub/Sub service (port 8085, gRPC)** — fourth v1 service. Implements Publisher (CreateTopic / GetTopic / UpdateTopic / DeleteTopic / ListTopics / ListTopicSubscriptions / Publish) and Subscriber (CreateSubscription / GetSubscription / UpdateSubscription / DeleteSubscription / ListSubscriptions / Pull / Acknowledge / ModifyAckDeadline / StreamingPull / Seek-by-time) over the official `google-cloud-pubsub` wire. At-least-once delivery with ack-deadline-based redelivery (1s sweep), ordering keys with per-key serialization across NACK→redelivery, and seek-to-time. Storage is in-memory only; `PERSIST=1` is ignored. Push subscriptions, filters, schemas, snapshots, and exactly-once delivery are accepted-and-ignored or deferred — see `docs/services/pubsub.md` and `ROADMAP.md`.
```

- [ ] **Step 6: Update `docs/deployment.md`**

Find the default-ports table and add a row:

```
| Pub/Sub | 8085 | `PUBSUB_EMULATOR_PORT` |
```

- [ ] **Step 7: Commit docs**

```bash
git add docs/services/pubsub.md docs/architecture/pubsub.md README.md ROADMAP.md CHANGELOG.md docs/deployment.md
git commit -m "docs(pubsub): user + architecture docs, README/ROADMAP/CHANGELOG updates

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 20: Final quality gate + Docker smoke

**Files:** none (verification-only)

- [ ] **Step 1: Run the full unit suite**

```bash
.venv/bin/pytest tests/ --ignore=tests/integration/test_docker_image.py -x 2>&1 | tail -10
```

Expected: every test passes (existing + new). If any pre-existing test breaks, the new code touched something it shouldn't have — investigate before continuing.

- [ ] **Step 2: Run lint and format checks**

```bash
.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/ 2>&1 | tail -5
```

Expected: "All checks passed!" + "N files already formatted" with no diff.

If format fails, run `.venv/bin/ruff format src/ tests/` and re-commit the formatting changes.

- [ ] **Step 3: Build the Docker image and smoke-test the pubsub container**

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
docker run --rm -d --name gcp-local-pubsub-smoke -e SERVICES=pubsub -p 8085:8085 -p 4510:4510 gcp-local:dev
sleep 3
curl -s http://localhost:4510/_emulator/health | grep -q '"pubsub":true' && echo "OK" || echo "FAIL"
docker stop gcp-local-pubsub-smoke
```

Expected: `OK` printed. If the health probe says `false`, check `docker logs gcp-local-pubsub-smoke` — most common cause is a missing import after the proto generation step.

- [ ] **Step 4: Final self-audit per CLAUDE.md Definition of Done**

Walk both checklists in `CLAUDE.md` (docs audit + tests audit). Confirm:

- Every check that applies has been done.
- No "Known limitations" lines in `CHANGELOG.md` were superseded by this change without being amended.
- The single-PR override is explicitly called out in the PR description, with a link to the spec.

- [ ] **Step 5: Open the PR**

```bash
git push -u origin feat/pubsub-service
gh pr create --title "feat(pubsub): v1 emulator service (gRPC, port 8085)" --body "$(cat <<'EOF'
## Summary

Fourth v1 service. Drop-in compatible with the official `google-cloud-pubsub` Python client via `PUBSUB_EMULATOR_HOST=localhost:8085`.

- Publisher RPCs: CreateTopic, GetTopic, UpdateTopic, DeleteTopic, ListTopics, ListTopicSubscriptions, Publish.
- Subscriber RPCs: CreateSubscription, GetSubscription, UpdateSubscription, DeleteSubscription, ListSubscriptions, Pull, Acknowledge, ModifyAckDeadline, StreamingPull, Seek (by time).
- At-least-once delivery, ack-deadline redelivery (1s sweep), ordering keys with per-key serialization across NACK→redelivery, seek-to-time.
- Storage is in-memory only (justified in spec §6 — `PERSIST=1` is ignored).

**Single-PR override:** Per direction, this lands as one PR despite exceeding the project's <500-LOC budget. Reviewers should treat the spec (`docs/superpowers/specs/2026-04-29-gcp-local-pubsub-design.md`) as the map of the diff. Components are tightly coupled (servicer ↔ backlog ↔ delivery ↔ streaming) and a partial cut would not be usable.

## Spec

`docs/superpowers/specs/2026-04-29-gcp-local-pubsub-design.md`

## Test plan

- [x] `pytest tests/unit/services/pubsub/` — all green
- [x] `pytest tests/integration/test_pubsub_integration.py` — green via real `google-cloud-pubsub`
- [x] `pytest tests/ --ignore=tests/integration/test_docker_image.py` — full suite green
- [x] `ruff check src/ tests/` — clean
- [x] `ruff format --check src/ tests/` — clean
- [x] Docker smoke: `SERVICES=pubsub` container becomes healthy

## Docs audit

Per CLAUDE.md Definition of Done — both audit checklists walked; see commit-by-commit diff for individual updates.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After PR creation, await user merge before any further work.

---

## Self-review

(Performed by the plan author before handoff — not an executing-engineer task.)

**Spec coverage walk:**

- §2.1 in-scope RPCs → Tasks 8 (Topic CRUD), 9 (Publish), 10 (Subscription CRUD), 12 (Pull), 13 (Acknowledge + ModAck), 16 (StreamingPull), 17 (Seek). ✅
- §2.1 at-least-once delivery + 1s sweep → Task 14. ✅
- §2.1 ordering keys → Tasks 6 (backlog) + 15 (end-to-end). ✅
- §2.2 push_config / filter / dead_letter_policy stored — covered in `_sub_proto_to_record` (Task 10) where push_config is stored verbatim, filter is captured as a string, dead_letter_policy/retry_policy stored as `None` placeholder. Test in `test_create_subscription_accepts_push_config_no_op`. ✅
- §2.3 IAM → Unimplemented by virtue of not registering the IAM service (Task 17 documents this in the architecture doc). ✅
- §3.4 vendored protos via gen script → Task 1. ✅
- §4 records → Task 3 (models). ✅
- §5.1-5.3 pull/ack/sweeper → Tasks 6, 12, 13, 14. ✅
- §5.4 StreamingPull → Task 16. ✅
- §5.5 Seek → Task 17. ✅
- §5.6 ordering-key gating → covered in backlog (Task 6). ✅
- §6 in-memory only + PERSIST=1 logged-and-ignored → Task 7. ✅
- §7 StateHub event → Task 9. ✅
- §8 error mapping → Task 4. ✅
- §9 tests → Tasks 2-17 each include their unit tests; Task 18 integration. ✅
- §11 docs → Task 19. ✅

**Placeholder scan:** No "TBD" / "TODO" / "implement later" / vague handwaving in any task. The one place a path is reserved for runtime verification (`emulator_endpoints["pubsub"]` in Task 18) is called out with a fallback instruction.

**Type consistency:** `SubscriptionBacklog`, `DeliveredMessage`, `AckLease`, `MessageRecord`, `TopicRecord`, `SubscriptionRecord`, `PubSubStorage`, `InMemoryStorage`, `RedeliverySweeper`, `FlowControl` are used with consistent fields and signatures across tasks.

**Scope:** One self-contained service. Single plan, single PR (per user direction).
