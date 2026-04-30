"""Unit tests for SubscriberServicer.Pull (Task 12)."""

import asyncio

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
        ),
        _Ctx(),
    )
    return publisher, subscriber


@pytest.mark.asyncio
async def test_pull_returns_published_message(env) -> None:
    publisher, subscriber = env
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"hello")],
        ),
        _Ctx(),
    )
    resp = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    assert len(resp.received_messages) == 1
    rm = resp.received_messages[0]
    assert rm.message.data == b"hello"
    assert rm.message.message_id == "topic-a-1"
    assert rm.ack_id  # non-empty


@pytest.mark.asyncio
async def test_pull_honors_max_messages(env) -> None:
    publisher, subscriber = env
    for i in range(5):
        await publisher.Publish(
            pubsub_pb2.PublishRequest(
                topic="projects/proj-a/topics/topic-a",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode())],
            ),
            _Ctx(),
        )
    resp = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
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
            subscription="projects/proj-a/subscriptions/sub-a",
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
                subscription="projects/proj-a/subscriptions/sub-a",
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
            topic="projects/proj-a/topics/topic-a",
            messages=[pubsub_pb2.PubsubMessage(data=b"wake")],
        ),
        _Ctx(),
    )
    resp = await asyncio.wait_for(pull_task, timeout=2.0)
    assert resp.received_messages[0].message.data == b"wake"


@pytest.mark.asyncio
async def test_pull_to_missing_subscription_aborts(env) -> None:
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
        await subscriber.Pull(
            pubsub_pb2.PullRequest(
                subscription="projects/proj-a/subscriptions/missing-sub",
                max_messages=1,
                return_immediately=True,
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND
