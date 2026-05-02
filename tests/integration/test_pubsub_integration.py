"""End-to-end Pub/Sub against the in-process emulator using google-cloud-pubsub.

The `emulator` fixture boots gcp-local in-process as an asyncio task on the test
event loop. google-cloud-pubsub clients are synchronous/blocking, so all calls
are dispatched via ``asyncio.to_thread`` to avoid starving the loop and the
emulator gRPC server.
"""

import asyncio
import os

import pytest
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import pubsub_v1


@pytest.fixture(autouse=True)
def _set_emulator_host(emulator_endpoints):
    """Expose the emulator's Pub/Sub gRPC endpoint via PUBSUB_EMULATOR_HOST."""
    host = emulator_endpoints["pubsub"]
    os.environ["PUBSUB_EMULATOR_HOST"] = host
    yield
    os.environ.pop("PUBSUB_EMULATOR_HOST", None)


async def test_publish_and_pull_round_trip() -> None:
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "rt-topic")
    sub_path = subscriber.subscription_path("test-proj", "rt-sub")

    await asyncio.to_thread(publisher.create_topic, request={"name": topic_path})
    await asyncio.to_thread(
        subscriber.create_subscription,
        request={"name": sub_path, "topic": topic_path, "ack_deadline_seconds": 10},
    )

    futures = [publisher.publish(topic_path, f"msg-{i}".encode()) for i in range(5)]
    for f in futures:
        await asyncio.to_thread(f.result, 5)

    pull = await asyncio.to_thread(
        subscriber.pull,
        request={"subscription": sub_path, "max_messages": 10, "return_immediately": True},
    )
    received = sorted(rm.message.data for rm in pull.received_messages)
    assert received == [b"msg-0", b"msg-1", b"msg-2", b"msg-3", b"msg-4"]

    await asyncio.to_thread(
        subscriber.acknowledge,
        request={
            "subscription": sub_path,
            "ack_ids": [rm.ack_id for rm in pull.received_messages],
        },
    )


async def test_streaming_pull_via_subscribe_callback() -> None:
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "stream-topic")
    sub_path = subscriber.subscription_path("test-proj", "stream-sub")

    await asyncio.to_thread(publisher.create_topic, request={"name": topic_path})
    await asyncio.to_thread(
        subscriber.create_subscription,
        request={"name": sub_path, "topic": topic_path},
    )

    received: list[bytes] = []

    def _cb(msg):
        received.append(msg.data)
        msg.ack()

    fut = subscriber.subscribe(sub_path, callback=_cb)
    try:
        publish_fut = publisher.publish(topic_path, b"streamed")
        await asyncio.to_thread(publish_fut.result, 5)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5
        while loop.time() < deadline and not received:
            await asyncio.sleep(0.05)
        assert received == [b"streamed"]
    finally:
        fut.cancel()


async def test_ordering_keys_serialize_per_key() -> None:
    publisher = pubsub_v1.PublisherClient(
        publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=True)
    )
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "ord-topic")
    sub_path = subscriber.subscription_path("test-proj", "ord-sub")

    await asyncio.to_thread(publisher.create_topic, request={"name": topic_path})
    await asyncio.to_thread(
        subscriber.create_subscription,
        request={
            "name": sub_path,
            "topic": topic_path,
            "enable_message_ordering": True,
        },
    )

    for i in range(3):
        publish_fut = publisher.publish(topic_path, f"k-{i}".encode(), ordering_key="key1")
        await asyncio.to_thread(publish_fut.result, 5)

    pull = await asyncio.to_thread(
        subscriber.pull,
        request={"subscription": sub_path, "max_messages": 10, "return_immediately": True},
    )
    # Only the FIRST same-key message should be delivered before any ack.
    assert len(pull.received_messages) == 1
    assert pull.received_messages[0].message.data == b"k-0"


async def test_get_topic_not_found_raises() -> None:
    publisher = pubsub_v1.PublisherClient()
    with pytest.raises(NotFound):
        await asyncio.to_thread(
            publisher.get_topic,
            request={"topic": publisher.topic_path("test-proj", "missing")},
        )


async def test_create_subscription_duplicate_raises() -> None:
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path("test-proj", "dup-topic")
    sub_path = subscriber.subscription_path("test-proj", "dup-sub")
    await asyncio.to_thread(publisher.create_topic, request={"name": topic_path})
    await asyncio.to_thread(
        subscriber.create_subscription,
        request={"name": sub_path, "topic": topic_path},
    )
    with pytest.raises(AlreadyExists):
        await asyncio.to_thread(
            subscriber.create_subscription,
            request={"name": sub_path, "topic": topic_path},
        )


# ---- Push subscription integration tests --------------------------------


async def _start_push_endpoint(handler) -> tuple["object", str]:
    """Spin up an aiohttp server on 127.0.0.1:0 returning ``(runner, url)``."""
    from aiohttp import web

    app = web.Application()
    app.router.add_post("/push", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    # Discover the bound port via the underlying socket.
    server = site._server  # aiohttp internal; same approach the project's e2e uses
    bound_port = server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{bound_port}/push"


async def test_push_subscription_delivers_to_http_endpoint() -> None:
    """Real google-cloud-pubsub publish → emulator POSTs to local aiohttp server."""
    import base64

    from aiohttp import web

    received: list[dict] = []
    received_event = asyncio.Event()

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        received.append(body)
        received_event.set()
        return web.Response(status=204)

    runner, push_url = await _start_push_endpoint(handler)
    try:
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        topic_path = publisher.topic_path("test-proj", "push-topic")
        sub_path = subscriber.subscription_path("test-proj", "push-sub")

        await asyncio.to_thread(publisher.create_topic, request={"name": topic_path})
        await asyncio.to_thread(
            subscriber.create_subscription,
            request={
                "name": sub_path,
                "topic": topic_path,
                "push_config": {"push_endpoint": push_url},
                "ack_deadline_seconds": 10,
            },
        )

        publish_fut = publisher.publish(topic_path, b"hello-push", region="us-east1")
        await asyncio.to_thread(publish_fut.result, 5)

        await asyncio.wait_for(received_event.wait(), timeout=10)

        assert len(received) == 1
        envelope = received[0]
        assert envelope["subscription"] == sub_path
        assert base64.b64decode(envelope["message"]["data"]) == b"hello-push"
        assert envelope["message"]["attributes"] == {"region": "us-east1"}
        # No extra delivery on the next sweep — the 204 already acked.
        await asyncio.sleep(1.5)
        assert len(received) == 1
    finally:
        await runner.cleanup()


async def test_push_subscription_redelivers_on_500() -> None:
    """A 500 response NACKs; the next pump tick redelivers the same message."""
    from aiohttp import web

    calls = 0
    second_received = asyncio.Event()

    async def handler(request: web.Request) -> web.Response:
        nonlocal calls
        await request.json()
        calls += 1
        if calls == 1:
            return web.Response(status=500)
        second_received.set()
        return web.Response(status=204)

    runner, push_url = await _start_push_endpoint(handler)
    try:
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        topic_path = publisher.topic_path("test-proj", "push-retry-topic")
        sub_path = subscriber.subscription_path("test-proj", "push-retry-sub")

        await asyncio.to_thread(publisher.create_topic, request={"name": topic_path})
        await asyncio.to_thread(
            subscriber.create_subscription,
            request={
                "name": sub_path,
                "topic": topic_path,
                "push_config": {"push_endpoint": push_url},
                "ack_deadline_seconds": 5,
            },
        )

        publish_fut = publisher.publish(topic_path, b"retry-me")
        await asyncio.to_thread(publish_fut.result, 5)

        await asyncio.wait_for(second_received.wait(), timeout=15)
        assert calls == 2
    finally:
        await runner.cleanup()
