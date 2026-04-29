"""Unit tests for PublisherServicer.Publish (Task 9)."""

import datetime as dt

import grpc
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
        pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _FakeContext()
    )
    req = pubsub_pb2.PublishRequest(
        topic="projects/proj-a/topics/topic-a",
        messages=[
            pubsub_pb2.PubsubMessage(data=b"a"),
            pubsub_pb2.PubsubMessage(data=b"b"),
        ],
    )
    resp = await servicer.Publish(req, _FakeContext())
    assert len(resp.message_ids) == 2
    # IDs are unique and sortable in publish order.
    assert resp.message_ids[0] != resp.message_ids[1]
    # Format is "<topic_id>-<seq>" starting at 1.
    assert resp.message_ids[0] == "topic-a-1"
    assert resp.message_ids[1] == "topic-a-2"


@pytest.mark.asyncio
async def test_publish_stamps_publish_time(env) -> None:
    servicer, _ = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _FakeContext()
    )
    before = dt.datetime.now(dt.UTC)
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"x")],
        ),
        _FakeContext(),
    )
    msgs = await servicer._storage.get_messages("proj-a", "topic-a")
    assert len(msgs) == 1
    assert msgs[0].publish_time >= before


@pytest.mark.asyncio
async def test_publish_to_missing_topic_aborts(env) -> None:
    servicer, _ = env

    class _Aborted(Exception):
        pass

    class _CapturingCtx:
        def __init__(self):
            self.code = None

        async def abort(self, code, details):
            self.code = code
            raise _Aborted()

    ctx = _CapturingCtx()
    with pytest.raises(_Aborted):
        await servicer.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/proj-a/topics/missing-topic",
                messages=[pubsub_pb2.PubsubMessage(data=b"x")],
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_publish_emits_state_hub_event(env) -> None:
    servicer, hub = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _FakeContext()
    )
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-a/topics/topic-a",
            messages=[
                pubsub_pb2.PubsubMessage(data=b"hello", attributes={"k": "v"}),
            ],
        ),
        _FakeContext(),
    )
    assert len(hub.published) == 1
    event, payload = hub.published[0]
    assert event == "pubsub.message.published"
    assert payload["topic"] == "projects/proj-a/topics/topic-a"
    assert payload["attributes"] == {"k": "v"}
    assert payload["size_bytes"] == len(b"hello")
    assert payload["message_id"] == "topic-a-1"
    # publish_time is ISO8601 string.
    assert isinstance(payload["publish_time"], str)
    dt.datetime.fromisoformat(payload["publish_time"])


@pytest.mark.asyncio
async def test_publish_preserves_ordering_key(env) -> None:
    servicer, _ = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _FakeContext()
    )
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"x", ordering_key="k1")],
        ),
        _FakeContext(),
    )
    msgs = await servicer._storage.get_messages("proj-a", "topic-a")
    assert msgs[0].ordering_key == "k1"


@pytest.mark.asyncio
async def test_publish_without_state_hub_does_not_emit() -> None:
    servicer = PublisherServicer(storage=InMemoryStorage())
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _FakeContext()
    )
    # Should not raise.
    resp = await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"x")],
        ),
        _FakeContext(),
    )
    assert resp.message_ids == ["topic-a-1"]


@pytest.mark.asyncio
async def test_publish_sets_deliverable_events_for_subscribers(env) -> None:
    import asyncio

    from gcp_local.services.pubsub.models import SubscriptionRecord

    servicer, _ = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _FakeContext()
    )
    # Insert a subscription record directly in storage (Task 10 adds CRUD).
    await servicer._storage.create_subscription(
        SubscriptionRecord(
            project="proj-a",
            subscription_id="sub-a",
            topic_project="proj-a",
            topic_id="topic-a",
            ack_deadline_seconds=10,
            enable_message_ordering=False,
            push_config=None,
            filter="",
            dead_letter_policy=None,
            retry_policy=None,
            labels={},
            enable_exactly_once_delivery=False,
            create_time=dt.datetime.now(dt.UTC),
        )
    )
    event = asyncio.Event()
    servicer.deliverable_events[("proj-a", "sub-a")] = event
    assert not event.is_set()
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"x")],
        ),
        _FakeContext(),
    )
    assert event.is_set()


@pytest.mark.asyncio
async def test_publish_stores_message_records(env) -> None:
    servicer, _ = env
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _FakeContext()
    )
    await servicer.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-a/topics/topic-a",
            messages=[
                pubsub_pb2.PubsubMessage(data=b"hi", attributes={"k": "v"}),
            ],
        ),
        _FakeContext(),
    )
    msgs = await servicer._storage.get_messages("proj-a", "topic-a")
    assert len(msgs) == 1
    rec = msgs[0]
    assert rec.message_id == "topic-a-1"
    assert rec.data == b"hi"
    assert rec.attributes == {"k": "v"}
    assert rec.ordering_key == ""
