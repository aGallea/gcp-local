"""Unit tests for SubscriberServicer.Acknowledge / ModifyAckDeadline (Task 13)."""

import datetime as dt

import grpc
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
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"a")],
        ),
        _Ctx(),
    )
    resp = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            max_messages=1,
            return_immediately=True,
        ),
        _Ctx(),
    )
    ack_id = resp.received_messages[0].ack_id
    await subscriber.Acknowledge(
        pubsub_pb2.AcknowledgeRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            ack_ids=[ack_id],
        ),
        _Ctx(),
    )
    # Forcibly sweep all leases (simulate 1h passing); ACKed message must not
    # come back.
    backlog, _ = await subscriber._get_backlog("proj-a", "sub-a")
    backlog.sweep_expired(now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1))
    resp2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
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
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"a")],
        ),
        _Ctx(),
    )
    r1 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            max_messages=1,
            return_immediately=True,
        ),
        _Ctx(),
    )
    ack_id = r1.received_messages[0].ack_id
    await subscriber.ModifyAckDeadline(
        pubsub_pb2.ModifyAckDeadlineRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            ack_ids=[ack_id],
            ack_deadline_seconds=0,
        ),
        _Ctx(),
    )
    r2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            max_messages=1,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert r2.received_messages[0].message.data == b"a"
    assert r2.received_messages[0].ack_id != ack_id  # new lease minted


@pytest.mark.asyncio
async def test_ack_unknown_id_is_noop(env) -> None:
    """Real Pub/Sub silently ignores unknown ack_ids (per Pub/Sub spec)."""
    _, subscriber = env
    # Should not raise.
    await subscriber.Acknowledge(
        pubsub_pb2.AcknowledgeRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            ack_ids=["bogus"],
        ),
        _Ctx(),
    )


@pytest.mark.asyncio
async def test_ack_to_missing_subscription_aborts(env) -> None:
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
                subscription="projects/proj-a/subscriptions/missing-sub",
                ack_ids=["x"],
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND
