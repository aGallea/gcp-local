import datetime as dt

import pytest

from gcp_local.services.pubsub.errors import (
    SubscriptionAlreadyExists,
    SubscriptionNotFound,
    TopicAlreadyExists,
    TopicNotFound,
)
from gcp_local.services.pubsub.models import (
    MessageRecord,
    SubscriptionRecord,
    TopicRecord,
)
from gcp_local.services.pubsub.storage import InMemoryStorage


def _topic(project: str = "p", tid: str = "t") -> TopicRecord:
    return TopicRecord(
        project=project,
        topic_id=tid,
        labels={},
        message_storage_policy=None,
        kms_key_name=None,
        schema_settings=None,
    )


def _subscription(
    project: str = "p",
    sid: str = "s",
    tid: str = "t",
    *,
    enable_ordering: bool = False,
) -> SubscriptionRecord:
    return SubscriptionRecord(
        project=project,
        subscription_id=sid,
        topic_project=project,
        topic_id=tid,
        ack_deadline_seconds=10,
        enable_message_ordering=enable_ordering,
        push_config=None,
        filter="",
        dead_letter_policy=None,
        retry_policy=None,
        labels={},
        enable_exactly_once_delivery=False,
        create_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
    )


@pytest.mark.asyncio
async def test_create_and_get_topic() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    got = await s.get_topic("p", "t")
    assert got.topic_id == "t"


@pytest.mark.asyncio
async def test_create_topic_duplicate_raises() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    with pytest.raises(TopicAlreadyExists):
        await s.create_topic(_topic())


@pytest.mark.asyncio
async def test_get_topic_missing_raises() -> None:
    s = InMemoryStorage()
    with pytest.raises(TopicNotFound):
        await s.get_topic("p", "missing")


@pytest.mark.asyncio
async def test_delete_topic_removes() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.delete_topic("p", "t")
    with pytest.raises(TopicNotFound):
        await s.get_topic("p", "t")


@pytest.mark.asyncio
async def test_list_topics_filtered_by_project() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic("p1", "a"))
    await s.create_topic(_topic("p1", "b"))
    await s.create_topic(_topic("p2", "c"))
    rows = await s.list_topics("p1")
    assert sorted(r.topic_id for r in rows) == ["a", "b"]


@pytest.mark.asyncio
async def test_create_subscription_requires_topic() -> None:
    s = InMemoryStorage()
    with pytest.raises(TopicNotFound):
        await s.create_subscription(_subscription())


@pytest.mark.asyncio
async def test_create_subscription_duplicate_raises() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.create_subscription(_subscription())
    with pytest.raises(SubscriptionAlreadyExists):
        await s.create_subscription(_subscription())


@pytest.mark.asyncio
async def test_get_subscription_missing_raises() -> None:
    s = InMemoryStorage()
    with pytest.raises(SubscriptionNotFound):
        await s.get_subscription("p", "missing")


@pytest.mark.asyncio
async def test_append_message_returns_monotonic_index() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    m1 = MessageRecord(
        message_id="t-1",
        publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=b"a",
        attributes={},
        ordering_key="",
    )
    m2 = MessageRecord(
        message_id="t-2",
        publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=b"b",
        attributes={},
        ordering_key="",
    )
    assert await s.append_message("p", "t", m1) == 0
    assert await s.append_message("p", "t", m2) == 1
    msgs = await s.get_messages("p", "t")
    assert [m.data for m in msgs] == [b"a", b"b"]


@pytest.mark.asyncio
async def test_list_subscriptions_for_topic() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.create_subscription(_subscription(sid="s1"))
    await s.create_subscription(_subscription(sid="s2"))
    names = await s.list_topic_subscriptions("p", "t")
    assert sorted(names) == ["projects/p/subscriptions/s1", "projects/p/subscriptions/s2"]


@pytest.mark.asyncio
async def test_reset_clears_everything() -> None:
    s = InMemoryStorage()
    await s.create_topic(_topic())
    await s.create_subscription(_subscription())
    await s.reset()
    assert await s.list_topics("p") == []
    assert await s.list_subscriptions("p") == []
