"""Tests for the SubscriberServicer.Seek RPC (time-based)."""

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
async def test_seek_to_time_rewinds_subscription(env) -> None:
    _, subscriber = env
    base = dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=dt.UTC)
    # Manually drive publish_time by writing through storage. The Publish RPC
    # uses datetime.now(); we patch via storage to control timing.
    from gcp_local.services.pubsub.models import MessageRecord

    for i in range(3):
        await subscriber._storage.append_message(
            "proj-a",
            "topic-a",
            MessageRecord(
                message_id=f"topic-a-{i}",
                publish_time=base + dt.timedelta(minutes=i),
                data=f"m{i}".encode(),
                attributes={},
                ordering_key="",
            ),
        )
    # Pull and ack everything.
    r = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
            max_messages=10,
            return_immediately=True,
        ),
        _Ctx(),
    )
    await subscriber.Acknowledge(
        pubsub_pb2.AcknowledgeRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
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
            subscription="projects/proj-a/subscriptions/sub-a",
            time=ts,
        ),
        _Ctx(),
    )
    assert seek_resp is not None  # SeekResponse is empty but non-None
    r2 = await subscriber.Pull(
        pubsub_pb2.PullRequest(
            subscription="projects/proj-a/subscriptions/sub-a",
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
                subscription="projects/proj-a/subscriptions/sub-a",
                snapshot="projects/proj-a/snapshots/snap-a",
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.UNIMPLEMENTED


@pytest.mark.asyncio
async def test_seek_without_time_or_snapshot_invalid_argument(env) -> None:
    _, subscriber = env
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.Seek(
            pubsub_pb2.SeekRequest(
                subscription="projects/proj-a/subscriptions/sub-a",
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.INVALID_ARGUMENT
