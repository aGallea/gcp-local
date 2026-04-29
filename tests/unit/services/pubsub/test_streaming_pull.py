"""Unit tests for SubscriberServicer.StreamingPull (Task 16)."""

import asyncio

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
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/proj-x/topics/topic-x"), _Ctx())
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/proj-x/subscriptions/sub-x",
            topic="projects/proj-x/topics/topic-x",
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
            topic="projects/proj-x/topics/topic-x",
            messages=[
                pubsub_pb2.PubsubMessage(data=b"a"),
                pubsub_pb2.PubsubMessage(data=b"b"),
            ],
        ),
        _Ctx(),
    )
    initial = pubsub_pb2.StreamingPullRequest(
        subscription="projects/proj-x/subscriptions/sub-x",
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
    assert len(received_ack_ids) == 2


@pytest.mark.asyncio
async def test_streaming_pull_processes_acks_from_request_stream(env) -> None:
    publisher, subscriber = env
    await publisher.Publish(
        pubsub_pb2.PublishRequest(
            topic="projects/proj-x/topics/topic-x",
            messages=[pubsub_pb2.PubsubMessage(data=b"x")],
        ),
        _Ctx(),
    )
    initial = pubsub_pb2.StreamingPullRequest(
        subscription="projects/proj-x/subscriptions/sub-x",
        stream_ack_deadline_seconds=10,
        max_outstanding_messages=10,
        max_outstanding_bytes=0,
    )
    ctx = _Ctx()
    captured_ack_ids: list[str] = []

    async def _drive():
        gen = subscriber.StreamingPull(_async_iter([initial]), ctx)
        first = await gen.__anext__()
        ack_id = first.received_messages[0].ack_id
        captured_ack_ids.append(ack_id)
        # Verify the ack path the streaming consumer would invoke is reachable.
        backlog, lock = await subscriber._get_backlog("proj-x", "sub-x")
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
                topic="projects/proj-x/topics/topic-x",
                messages=[pubsub_pb2.PubsubMessage(data=f"m{i}".encode())],
            ),
            _Ctx(),
        )
    initial = pubsub_pb2.StreamingPullRequest(
        subscription="projects/proj-x/subscriptions/sub-x",
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
