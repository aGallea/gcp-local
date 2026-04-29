import grpc
import pytest

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2
from gcp_local.services.pubsub.servicer import PublisherServicer
from gcp_local.services.pubsub.storage import InMemoryStorage


class _FakeContext:
    """Minimal stand-in for grpc.aio.ServicerContext — captures abort calls."""

    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise _Aborted()


class _Aborted(Exception):
    pass


@pytest.fixture
def servicer() -> PublisherServicer:
    return PublisherServicer(storage=InMemoryStorage())


@pytest.mark.asyncio
async def test_create_topic_returns_topic_with_name(servicer: PublisherServicer) -> None:
    req = pubsub_pb2.Topic(name="projects/p/topics/topic-a", labels={"env": "dev"})
    resp = await servicer.CreateTopic(req, _FakeContext())
    assert resp.name == "projects/p/topics/topic-a"
    assert resp.labels["env"] == "dev"


@pytest.mark.asyncio
async def test_create_topic_duplicate_aborts_already_exists(
    servicer: PublisherServicer,
) -> None:
    req = pubsub_pb2.Topic(name="projects/p/topics/topic-a")
    await servicer.CreateTopic(req, _FakeContext())
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.CreateTopic(req, ctx)
    assert ctx.aborted is not None
    assert ctx.aborted[0] == grpc.StatusCode.ALREADY_EXISTS


@pytest.mark.asyncio
async def test_create_topic_invalid_name_aborts(servicer: PublisherServicer) -> None:
    req = pubsub_pb2.Topic(name="garbage")
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.CreateTopic(req, ctx)
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_create_topic_rejects_goog_prefix(servicer: PublisherServicer) -> None:
    req = pubsub_pb2.Topic(name="projects/p/topics/goog-reserved")
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.CreateTopic(req, ctx)
    assert ctx.aborted[0] == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_get_topic_missing_aborts_not_found(servicer: PublisherServicer) -> None:
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetTopic(pubsub_pb2.GetTopicRequest(topic="projects/p/topics/missing"), ctx)
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_get_topic_returns_record(servicer: PublisherServicer) -> None:
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/topic-a", labels={"k": "v"}),
        _FakeContext(),
    )
    resp = await servicer.GetTopic(
        pubsub_pb2.GetTopicRequest(topic="projects/p/topics/topic-a"), _FakeContext()
    )
    assert resp.labels["k"] == "v"


@pytest.mark.asyncio
async def test_update_topic_changes_labels(servicer: PublisherServicer) -> None:
    await servicer.CreateTopic(
        pubsub_pb2.Topic(name="projects/p/topics/topic-a", labels={"a": "1"}),
        _FakeContext(),
    )
    update_req = pubsub_pb2.UpdateTopicRequest(
        topic=pubsub_pb2.Topic(name="projects/p/topics/topic-a", labels={"a": "2"}),
        update_mask={"paths": ["labels"]},  # FieldMask is constructed via proto helper
    )
    resp = await servicer.UpdateTopic(update_req, _FakeContext())
    assert resp.labels["a"] == "2"


@pytest.mark.asyncio
async def test_delete_topic_removes(servicer: PublisherServicer) -> None:
    await servicer.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/topic-a"), _FakeContext())
    await servicer.DeleteTopic(
        pubsub_pb2.DeleteTopicRequest(topic="projects/p/topics/topic-a"),
        _FakeContext(),
    )
    ctx = _FakeContext()
    with pytest.raises(_Aborted):
        await servicer.GetTopic(pubsub_pb2.GetTopicRequest(topic="projects/p/topics/topic-a"), ctx)
    assert ctx.aborted[0] == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_list_topics_pagination(servicer: PublisherServicer) -> None:
    for i in range(3):
        await servicer.CreateTopic(
            pubsub_pb2.Topic(name=f"projects/p/topics/topic-{i}"), _FakeContext()
        )
    resp = await servicer.ListTopics(
        pubsub_pb2.ListTopicsRequest(project="projects/p", page_size=2),
        _FakeContext(),
    )
    assert len(resp.topics) == 2
    assert resp.next_page_token != ""
    resp2 = await servicer.ListTopics(
        pubsub_pb2.ListTopicsRequest(
            project="projects/p", page_size=2, page_token=resp.next_page_token
        ),
        _FakeContext(),
    )
    assert len(resp2.topics) == 1
    assert resp2.next_page_token == ""


@pytest.mark.asyncio
async def test_list_topic_subscriptions_returns_names_only(
    servicer: PublisherServicer,
) -> None:
    """Verifies the wire shape — ListTopicSubscriptions returns subscription
    names (strings), not Subscription messages."""
    await servicer.CreateTopic(pubsub_pb2.Topic(name="projects/p/topics/topic-a"), _FakeContext())
    # We need to add a subscription via the storage layer directly since
    # SubscriberServicer.CreateSubscription isn't wired up yet.
    import datetime as dt

    from gcp_local.services.pubsub.models import SubscriptionRecord

    await servicer._storage.create_subscription(
        SubscriptionRecord(
            project="p",
            subscription_id="sub-a",
            topic_project="p",
            topic_id="topic-a",
            ack_deadline_seconds=10,
            enable_message_ordering=False,
            push_config=None,
            filter="",
            dead_letter_policy=None,
            retry_policy=None,
            labels={},
            enable_exactly_once_delivery=False,
            create_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        )
    )
    resp = await servicer.ListTopicSubscriptions(
        pubsub_pb2.ListTopicSubscriptionsRequest(topic="projects/p/topics/topic-a"),
        _FakeContext(),
    )
    assert list(resp.subscriptions) == ["projects/p/subscriptions/sub-a"]
