"""End-to-end ordering-key serialization tests (Task 15).

Ordering logic was added in Task 6 (backlog) and exercised by `test_backlog.py`.
These tests assert the Publish -> Pull -> Ack -> Pull flow at the servicer
level so the wiring through `PublisherServicer` and `SubscriberServicer` is
verified end-to-end.
"""

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
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/proj-a/subscriptions/sub-a",
            topic="projects/proj-a/topics/topic-a",
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
                topic="projects/proj-a/topics/topic-a",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode(), ordering_key="k1")],
            ),
            _Ctx(),
        )
    # Pull all -> should only get the FIRST message; the other two are blocked
    # behind the same ordering key until the first is acked.
    r1 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
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
            subscription="projects/proj-a/subscriptions/sub-a",
            ack_ids=[r1.received_messages[0].ack_id],
        ),
        _Ctx(),
    )
    r2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert [rm.message.data for rm in r2.received_messages] == [b"m1"]


@pytest.mark.asyncio
async def test_ordering_disabled_returns_all_at_once() -> None:
    """Sanity check: a non-ordering subscription gets everything regardless of key."""
    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/proj-a/topics/topic-a"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/proj-a/subscriptions/sub-a",
            topic="projects/proj-a/topics/topic-a",
            enable_message_ordering=False,
        ),
        _Ctx(),
    )
    for i in range(3):
        await publisher.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/proj-a/topics/topic-a",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode(), ordering_key="k1")],
            ),
            _Ctx(),
        )
    r = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert sorted(rm.message.data for rm in r.received_messages) == [
        b"m0",
        b"m1",
        b"m2",
    ]
