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
