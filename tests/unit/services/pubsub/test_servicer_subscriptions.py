"""Unit tests for SubscriberServicer subscription CRUD RPCs."""

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
    await publisher.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/topic-a"), _Ctx())
    return publisher, subscriber


@pytest.mark.asyncio
async def test_create_subscription_happy(env) -> None:
    _, subscriber = env
    req = pubsub_pb2.Subscription(
        name="projects/p/subscriptions/sub-a",
        topic="projects/p/topics/topic-a",
        ack_deadline_seconds=20,
        labels={"env": "dev"},
    )
    resp = await subscriber.CreateSubscription(req, _Ctx())
    assert resp.name == "projects/p/subscriptions/sub-a"
    assert resp.ack_deadline_seconds == 20
    assert resp.topic == "projects/p/topics/topic-a"
    assert dict(resp.labels) == {"env": "dev"}


@pytest.mark.asyncio
async def test_create_subscription_default_ack_deadline(env) -> None:
    _, subscriber = env
    resp = await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/sub-a",
            topic="projects/p/topics/topic-a",
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
                name="projects/p/subscriptions/sub-a",
                topic="projects/p/topics/missing-topic",
            ),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_create_subscription_duplicate_aborts(env) -> None:
    _, subscriber = env
    req = pubsub_pb2.Subscription(
        name="projects/p/subscriptions/sub-a",
        topic="projects/p/topics/topic-a",
    )
    await subscriber.CreateSubscription(req, _Ctx())
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.CreateSubscription(req, ctx)
    assert ctx.code == grpc.StatusCode.ALREADY_EXISTS


@pytest.mark.asyncio
async def test_create_subscription_accepts_push_config(env) -> None:
    """pushConfig round-trips through CreateSubscription / GetSubscription.

    Push delivery itself is exercised in :mod:`tests.unit.services.pubsub.test_push`;
    this test only asserts that the field round-trips on the wire. We inject an
    httpx mock transport so the pump that ``_ensure_pump`` starts does not try
    to POST to the (real) example.com endpoint.
    """
    import httpx

    _, subscriber = env
    subscriber._push_transport_factory = lambda: httpx.MockTransport(
        lambda r: httpx.Response(200)
    )
    try:
        req = pubsub_pb2.Subscription(
            name="projects/p/subscriptions/sub-a",
            topic="projects/p/topics/topic-a",
            push_config=pubsub_pb2.PushConfig(push_endpoint="https://example.com/hook"),
        )
        resp = await subscriber.CreateSubscription(req, _Ctx())
        assert resp.push_config.push_endpoint == "https://example.com/hook"
    finally:
        # Stop the pump the create-subscription RPC started so asyncio teardown
        # doesn't see a dangling task.
        pump = subscriber._pumps.pop(("p", "sub-a"), None)
        if pump is not None:
            await pump.stop()


@pytest.mark.asyncio
async def test_get_subscription_returns_record(env) -> None:
    _, subscriber = env
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/sub-a",
            topic="projects/p/topics/topic-a",
            ack_deadline_seconds=15,
        ),
        _Ctx(),
    )
    resp = await subscriber.GetSubscription(
        pubsub_pb2.GetSubscriptionRequest(subscription="projects/p/subscriptions/sub-a"),
        _Ctx(),
    )
    assert resp.name == "projects/p/subscriptions/sub-a"
    assert resp.ack_deadline_seconds == 15


@pytest.mark.asyncio
async def test_get_subscription_missing_aborts(env) -> None:
    _, subscriber = env
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.GetSubscription(
            pubsub_pb2.GetSubscriptionRequest(subscription="projects/p/subscriptions/missing-sub"),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_update_subscription_changes_ack_deadline(env) -> None:
    _, subscriber = env
    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/sub-a",
            topic="projects/p/topics/topic-a",
            ack_deadline_seconds=10,
        ),
        _Ctx(),
    )
    update_req = pubsub_pb2.UpdateSubscriptionRequest(
        subscription=pubsub_pb2.Subscription(
            name="projects/p/subscriptions/sub-a",
            topic="projects/p/topics/topic-a",
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
            name="projects/p/subscriptions/sub-a",
            topic="projects/p/topics/topic-a",
        ),
        _Ctx(),
    )
    await subscriber.DeleteSubscription(
        pubsub_pb2.DeleteSubscriptionRequest(subscription="projects/p/subscriptions/sub-a"),
        _Ctx(),
    )
    ctx = _Ctx()
    with pytest.raises(_Aborted):
        await subscriber.GetSubscription(
            pubsub_pb2.GetSubscriptionRequest(subscription="projects/p/subscriptions/sub-a"),
            ctx,
        )
    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_list_subscriptions_pagination(env) -> None:
    _, subscriber = env
    for sid in ("sub-a", "sub-b", "sub-c"):
        await subscriber.CreateSubscription(
            pubsub_pb2.Subscription(
                name=f"projects/p/subscriptions/{sid}",
                topic="projects/p/topics/topic-a",
            ),
            _Ctx(),
        )
    resp = await subscriber.ListSubscriptions(
        pubsub_pb2.ListSubscriptionsRequest(project="projects/p", page_size=2),
        _Ctx(),
    )
    assert len(resp.subscriptions) == 2
    assert resp.next_page_token != ""
    # Second page returns the remaining one and clears the token.
    resp2 = await subscriber.ListSubscriptions(
        pubsub_pb2.ListSubscriptionsRequest(
            project="projects/p", page_size=2, page_token=resp.next_page_token
        ),
        _Ctx(),
    )
    assert len(resp2.subscriptions) == 1
    assert resp2.next_page_token == ""
