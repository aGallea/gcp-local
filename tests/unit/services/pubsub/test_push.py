"""Unit tests for the push subscription pump."""

import asyncio
import base64
import datetime as dt
import json

import httpx
import pytest

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
from gcp_local.services.pubsub.engine.push import PushPump
from gcp_local.services.pubsub.models import MessageRecord


def _msg(
    seq: int,
    data: bytes = b"hi",
    ordering_key: str = "",
    attributes: dict[str, str] | None = None,
) -> MessageRecord:
    return MessageRecord(
        message_id=f"t-{seq}",
        publish_time=dt.datetime(2026, 5, 2, 12, 0, 0, tzinfo=dt.UTC),
        data=data,
        attributes=attributes or {},
        ordering_key=ordering_key,
    )


async def _wait_for(predicate, *, timeout: float = 1.0, interval: float = 0.005) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"timed out waiting for {predicate!r}")


@pytest.mark.asyncio
async def test_push_payload_shape_matches_real_pubsub_envelope() -> None:
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1, data=b"hello", attributes={"region": "us-east1"})]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/sub",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(lambda: len(received) == 1)
    finally:
        await pump.stop()

    request = received[0]
    assert request.method == "POST"
    assert request.url == httpx.URL("http://example.test/push")
    assert request.headers["content-type"] == "application/json"

    body = json.loads(request.content)
    assert body["subscription"] == "projects/p/subscriptions/sub"
    assert body["message"]["messageId"] == "t-1"
    assert base64.b64decode(body["message"]["data"]) == b"hello"
    assert body["message"]["attributes"] == {"region": "us-east1"}
    assert body["message"]["publishTime"] == "2026-05-02T12:00:00Z"
    assert "orderingKey" not in body["message"]


@pytest.mark.asyncio
async def test_push_acks_on_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1)]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/sub",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(
            lambda: backlog._cursor == 1 and not backlog._leases and not backlog._nacked
        )
    finally:
        await pump.stop()


@pytest.mark.asyncio
async def test_push_nacks_on_non_2xx_and_redelivers() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500) if calls == 1 else httpx.Response(200)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1)]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/sub",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(lambda: calls >= 2 and not backlog._leases and not backlog._nacked)
    finally:
        await pump.stop()

    assert calls == 2


@pytest.mark.asyncio
async def test_push_nacks_on_timeout() -> None:
    """A transport-level ReadTimeout NACKs the message.

    The handler raises ReadTimeout once on the first call, then succeeds.
    This isolates the timeout-handling path without spinning the pump in a
    tight retry loop the test fixture has to fight against.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("simulated", request=request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    messages = [_msg(1)]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/sub",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
        post_timeout_seconds=0.05,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(lambda: calls >= 2 and not backlog._leases and not backlog._nacked)
    finally:
        await pump.stop()

    assert calls == 2  # first call raised timeout → NACK, second succeeded → ack


@pytest.mark.asyncio
async def test_push_serializes_messages_with_same_ordering_key() -> None:
    received_order: list[str] = []
    release_first = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        received_order.append(body["message"]["messageId"])
        if body["message"]["messageId"] == "t-1":
            await release_first.wait()
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    backlog = SubscriptionBacklog(ack_deadline_seconds=30, enable_ordering=True)
    messages = [_msg(1, ordering_key="k"), _msg(2, ordering_key="k")]

    pump = PushPump(
        subscription_name="projects/p/subscriptions/sub",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: messages,
        transport=transport,
    )
    await pump.start()
    try:
        backlog.deliverable.set()
        await _wait_for(lambda: len(received_order) == 1)
        assert received_order == ["t-1"]
        # While first is in-flight, second must NOT have been POSTed yet.
        await asyncio.sleep(0.05)
        assert received_order == ["t-1"]
        release_first.set()
        await _wait_for(lambda: len(received_order) == 2)
    finally:
        await pump.stop()

    assert received_order == ["t-1", "t-2"]


@pytest.mark.asyncio
async def test_push_pump_stop_cancels_task_cleanly() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    pump = PushPump(
        subscription_name="projects/p/subscriptions/sub",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: [],
        transport=transport,
    )
    await pump.start()
    assert pump._task is not None and not pump._task.done()
    await pump.stop()
    assert pump._task is None


class _NoopServicerContext:
    """Just enough of grpc.aio.ServicerContext for these tests."""

    async def abort(self, code, msg):
        raise AssertionError(f"abort {code}: {msg}")


@pytest.mark.asyncio
async def test_servicer_starts_pump_when_create_subscription_has_push_config() -> None:
    from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
    from gcp_local.services.pubsub.models import TopicRecord
    from gcp_local.services.pubsub.servicer import PublisherServicer, SubscriberServicer
    from gcp_local.services.pubsub.storage import InMemoryStorage

    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage, state_hub=None)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await storage.create_topic(
        TopicRecord(
            project="p",
            topic_id="topic",
            labels={},
            message_storage_policy=None,
            kms_key_name=None,
            schema_settings=None,
        )
    )

    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    subscriber._push_transport_factory = lambda: httpx.MockTransport(handler)

    sub = pubsub_pb2.Subscription(
        name="projects/p/subscriptions/sub",
        topic="projects/p/topics/topic",
        push_config=pubsub_pb2.PushConfig(push_endpoint="http://example.test/push"),
        ack_deadline_seconds=10,
    )

    await subscriber.CreateSubscription(sub, _NoopServicerContext())
    assert ("p", "sub") in subscriber._pumps

    await storage.append_message(
        "p",
        "topic",
        MessageRecord(
            message_id="t-1",
            publish_time=dt.datetime.now(dt.UTC),
            data=b"hi",
            attributes={},
            ordering_key="",
        ),
    )
    subscriber._backlogs[("p", "sub")].deliverable.set()
    await _wait_for(lambda: len(received) == 1)

    await subscriber.DeleteSubscription(
        pubsub_pb2.DeleteSubscriptionRequest(subscription="projects/p/subscriptions/sub"),
        _NoopServicerContext(),
    )
    assert ("p", "sub") not in subscriber._pumps


@pytest.mark.asyncio
async def test_servicer_swaps_pump_when_update_subscription_changes_push_endpoint() -> None:
    from google.protobuf import field_mask_pb2

    from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
    from gcp_local.services.pubsub.models import TopicRecord
    from gcp_local.services.pubsub.servicer import PublisherServicer, SubscriberServicer
    from gcp_local.services.pubsub.storage import InMemoryStorage

    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage, state_hub=None)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await storage.create_topic(
        TopicRecord(
            project="p",
            topic_id="topic",
            labels={},
            message_storage_policy=None,
            kms_key_name=None,
            schema_settings=None,
        )
    )

    subscriber._push_transport_factory = lambda: httpx.MockTransport(lambda r: httpx.Response(200))

    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/sub",
            topic="projects/p/topics/topic",
            push_config=pubsub_pb2.PushConfig(push_endpoint="http://a.test/push"),
            ack_deadline_seconds=10,
        ),
        _NoopServicerContext(),
    )
    pump_a = subscriber._pumps[("p", "sub")]
    assert pump_a.push_endpoint == "http://a.test/push"

    await subscriber.UpdateSubscription(
        pubsub_pb2.UpdateSubscriptionRequest(
            subscription=pubsub_pb2.Subscription(
                name="projects/p/subscriptions/sub",
                push_config=pubsub_pb2.PushConfig(push_endpoint="http://b.test/push"),
            ),
            update_mask=field_mask_pb2.FieldMask(paths=["push_config"]),
        ),
        _NoopServicerContext(),
    )
    pump_b = subscriber._pumps[("p", "sub")]
    assert pump_b is not pump_a
    assert pump_b.push_endpoint == "http://b.test/push"
    assert pump_a._task is None  # old pump stopped


@pytest.mark.asyncio
async def test_servicer_stops_pump_when_update_clears_push_config() -> None:
    from google.protobuf import field_mask_pb2

    from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
    from gcp_local.services.pubsub.models import TopicRecord
    from gcp_local.services.pubsub.servicer import PublisherServicer, SubscriberServicer
    from gcp_local.services.pubsub.storage import InMemoryStorage

    storage = InMemoryStorage()
    publisher = PublisherServicer(storage=storage, state_hub=None)
    subscriber = SubscriberServicer(storage=storage, publisher=publisher)
    await storage.create_topic(
        TopicRecord(
            project="p",
            topic_id="topic",
            labels={},
            message_storage_policy=None,
            kms_key_name=None,
            schema_settings=None,
        )
    )
    subscriber._push_transport_factory = lambda: httpx.MockTransport(lambda r: httpx.Response(200))

    await subscriber.CreateSubscription(
        pubsub_pb2.Subscription(
            name="projects/p/subscriptions/sub",
            topic="projects/p/topics/topic",
            push_config=pubsub_pb2.PushConfig(push_endpoint="http://a.test/push"),
            ack_deadline_seconds=10,
        ),
        _NoopServicerContext(),
    )
    assert ("p", "sub") in subscriber._pumps

    await subscriber.UpdateSubscription(
        pubsub_pb2.UpdateSubscriptionRequest(
            subscription=pubsub_pb2.Subscription(
                name="projects/p/subscriptions/sub",
                push_config=pubsub_pb2.PushConfig(),  # cleared
            ),
            update_mask=field_mask_pb2.FieldMask(paths=["push_config"]),
        ),
        _NoopServicerContext(),
    )
    assert ("p", "sub") not in subscriber._pumps


@pytest.mark.asyncio
async def test_service_stop_cancels_all_pumps(tmp_path) -> None:
    from gcp_local.core.context import Context
    from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
    from gcp_local.services.pubsub.service import PubSubService

    svc = PubSubService()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"pubsub": 0})
    await svc.start(ctx)
    try:
        assert svc._subscriber is not None
        backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
        pump = PushPump(
            subscription_name="projects/p/subscriptions/sub",
            push_endpoint="http://example.test/push",
            backlog=backlog,
            get_messages=lambda: [],
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        await pump.start()
        svc._subscriber._pumps[("p", "sub")] = pump
    finally:
        await svc.stop()

    assert pump._task is None


@pytest.mark.asyncio
async def test_push_pump_double_start_is_idempotent() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    pump = PushPump(
        subscription_name="projects/p/subscriptions/sub",
        push_endpoint="http://example.test/push",
        backlog=backlog,
        get_messages=lambda: [],
        transport=transport,
    )
    await pump.start()
    first_task = pump._task
    await pump.start()
    assert pump._task is first_task
    await pump.stop()
