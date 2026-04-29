"""Pub/Sub gRPC servicers."""

import asyncio
import base64
import datetime as dt
import itertools
from collections import defaultdict
from typing import Any, NoReturn, Protocol

import grpc

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2, pubsub_pb2_grpc
from gcp_local.services.pubsub.engine.backlog import (
    DeliveredMessage,
    SubscriptionBacklog,
)
from gcp_local.services.pubsub.errors import (
    InvalidArgument,
    PubSubError,
    grpc_code_for,
)
from gcp_local.services.pubsub.models import MessageRecord, SubscriptionRecord, TopicRecord
from gcp_local.services.pubsub.names import (
    InvalidName,
    parse_subscription_name,
    parse_topic_name,
    validate_resource_id,
)
from gcp_local.services.pubsub.storage import PubSubStorage

_LONG_POLL_TIMEOUT_SECONDS = 90.0


class _StateHubLike(Protocol):
    async def publish(self, event: str, payload: dict) -> None: ...


async def _abort(context: grpc.aio.ServicerContext, exc: Exception) -> NoReturn:
    code = grpc.StatusCode.INVALID_ARGUMENT if isinstance(exc, InvalidName) else grpc_code_for(exc)
    await context.abort(code, str(exc))
    raise AssertionError("unreachable")  # context.abort always raises


def _parse_topic(name: str) -> tuple[str, str]:
    try:
        project, topic_id = parse_topic_name(name)
    except InvalidName as e:
        raise e
    validate_resource_id(topic_id)
    return project, topic_id


def _encode_token(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def _decode_token(token: str) -> int:
    if not token:
        return 0
    try:
        return int(base64.urlsafe_b64decode(token.encode()).decode())
    except (ValueError, UnicodeDecodeError) as e:
        raise InvalidArgument(f"Invalid page_token: {token!r}") from e


def _topic_record_to_proto(rec: TopicRecord) -> pubsub_pb2.Topic:
    return pubsub_pb2.Topic(
        name=f"projects/{rec.project}/topics/{rec.topic_id}",
        labels=dict(rec.labels),
    )


def _topic_proto_to_record(msg: pubsub_pb2.Topic) -> TopicRecord:
    project, topic_id = _parse_topic(msg.name)
    return TopicRecord(
        project=project,
        topic_id=topic_id,
        labels=dict(msg.labels),
        message_storage_policy=None,
        kms_key_name=msg.kms_key_name or None,
        schema_settings=None,
    )


def _parse_subscription(name: str) -> tuple[str, str]:
    project, sub_id = parse_subscription_name(name)
    validate_resource_id(sub_id)
    return project, sub_id


def _sub_record_to_proto(rec: SubscriptionRecord) -> pubsub_pb2.Subscription:
    proto = pubsub_pb2.Subscription(
        name=f"projects/{rec.project}/subscriptions/{rec.subscription_id}",
        topic=f"projects/{rec.topic_project}/topics/{rec.topic_id}",
        ack_deadline_seconds=rec.ack_deadline_seconds,
        enable_message_ordering=rec.enable_message_ordering,
        filter=rec.filter,
        labels=dict(rec.labels),
        enable_exactly_once_delivery=rec.enable_exactly_once_delivery,
    )
    if rec.push_config is not None:
        proto.push_config.CopyFrom(pubsub_pb2.PushConfig(**rec.push_config))
    return proto


def _sub_proto_to_record(msg: pubsub_pb2.Subscription) -> SubscriptionRecord:
    sub_proj, sub_id = _parse_subscription(msg.name)
    topic_proj, topic_id = _parse_topic(msg.topic)
    push_config: dict[str, Any] | None = None
    if msg.HasField("push_config"):
        push_config = {"push_endpoint": msg.push_config.push_endpoint}
        if msg.push_config.attributes:
            push_config["attributes"] = dict(msg.push_config.attributes)
    return SubscriptionRecord(
        project=sub_proj,
        subscription_id=sub_id,
        topic_project=topic_proj,
        topic_id=topic_id,
        ack_deadline_seconds=msg.ack_deadline_seconds or 10,
        enable_message_ordering=msg.enable_message_ordering,
        push_config=push_config,
        filter=msg.filter or "",
        dead_letter_policy=None,
        retry_policy=None,
        labels=dict(msg.labels),
        enable_exactly_once_delivery=msg.enable_exactly_once_delivery,
        create_time=dt.datetime.now(dt.UTC),
    )


class PublisherServicer(pubsub_pb2_grpc.PublisherServicer):
    def __init__(
        self,
        *,
        storage: PubSubStorage,
        state_hub: _StateHubLike | None = None,
    ) -> None:
        self._storage = storage
        self._state_hub = state_hub
        # Per-topic monotonic message-id counters. Keyed by (project, topic_id).
        self._counters: dict[tuple[str, str], itertools.count] = defaultdict(
            lambda: itertools.count(1)
        )
        # asyncio.Event per (project, sub_id) registered by SubscriberServicer
        # so Pull / StreamingPull can wake on Publish. Set by the subscriber side
        # at first-pull time.
        self.deliverable_events: dict[tuple[str, str], asyncio.Event] = {}

    async def CreateTopic(
        self,
        request: pubsub_pb2.Topic,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Topic:
        try:
            rec = _topic_proto_to_record(request)
            await self._storage.create_topic(rec)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _topic_record_to_proto(rec)

    async def GetTopic(
        self,
        request: pubsub_pb2.GetTopicRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Topic:
        try:
            project, topic_id = _parse_topic(request.topic)
            rec = await self._storage.get_topic(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _topic_record_to_proto(rec)

    async def UpdateTopic(
        self,
        request: pubsub_pb2.UpdateTopicRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Topic:
        try:
            project, topic_id = _parse_topic(request.topic.name)
            existing = await self._storage.get_topic(project, topic_id)
            paths = set(request.update_mask.paths)
            updated = TopicRecord(
                project=existing.project,
                topic_id=existing.topic_id,
                labels=dict(request.topic.labels) if "labels" in paths else dict(existing.labels),
                message_storage_policy=existing.message_storage_policy,
                kms_key_name=existing.kms_key_name,
                schema_settings=existing.schema_settings,
            )
            await self._storage.update_topic(updated)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _topic_record_to_proto(updated)

    async def DeleteTopic(
        self,
        request: pubsub_pb2.DeleteTopicRequest,
        context: grpc.aio.ServicerContext,
    ):
        from google.protobuf import empty_pb2

        try:
            project, topic_id = _parse_topic(request.topic)
            await self._storage.delete_topic(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return empty_pb2.Empty()

    async def ListTopics(
        self,
        request: pubsub_pb2.ListTopicsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.ListTopicsResponse:
        if not request.project.startswith("projects/"):
            await _abort(context, InvalidArgument(f"Invalid project: {request.project!r}"))
        project = request.project[len("projects/") :]
        try:
            offset = _decode_token(request.page_token)
        except InvalidArgument as e:
            await _abort(context, e)
        page_size = request.page_size or 100
        rows = sorted(
            await self._storage.list_topics(project),
            key=lambda r: r.topic_id,
        )
        slice_ = rows[offset : offset + page_size]
        next_token = _encode_token(offset + page_size) if offset + page_size < len(rows) else ""
        return pubsub_pb2.ListTopicsResponse(
            topics=[_topic_record_to_proto(r) for r in slice_],
            next_page_token=next_token,
        )

    async def ListTopicSubscriptions(
        self,
        request: pubsub_pb2.ListTopicSubscriptionsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.ListTopicSubscriptionsResponse:
        try:
            project, topic_id = _parse_topic(request.topic)
            # Verify topic exists before listing.
            await self._storage.get_topic(project, topic_id)
            names = await self._storage.list_topic_subscriptions(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return pubsub_pb2.ListTopicSubscriptionsResponse(subscriptions=sorted(names))

    async def Publish(
        self,
        request: pubsub_pb2.PublishRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.PublishResponse:
        try:
            project, topic_id = _parse_topic(request.topic)
            # Verify topic exists.
            await self._storage.get_topic(project, topic_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)

        message_ids: list[str] = []
        counter = self._counters[(project, topic_id)]
        for proto_msg in request.messages:
            seq = next(counter)
            mid = f"{topic_id}-{seq}"
            now = dt.datetime.now(dt.UTC)
            rec = MessageRecord(
                message_id=mid,
                publish_time=now,
                data=bytes(proto_msg.data),
                attributes=dict(proto_msg.attributes),
                ordering_key=proto_msg.ordering_key or "",
            )
            await self._storage.append_message(project, topic_id, rec)
            message_ids.append(mid)
            if self._state_hub is not None:
                await self._state_hub.publish(
                    "pubsub.message.published",
                    {
                        "topic": request.topic,
                        "message_id": mid,
                        "attributes": dict(proto_msg.attributes),
                        "size_bytes": len(proto_msg.data),
                        "publish_time": now.isoformat(),
                    },
                )

        # Wake any waiting Pull / StreamingPull on subscriptions of this topic.
        # The SubscriberServicer registers Events keyed by (sub_project, sub_id);
        # we look up subs that point at this topic via storage.
        sub_names = await self._storage.list_topic_subscriptions(project, topic_id)
        for full_name in sub_names:
            # parse "projects/<p>/subscriptions/<s>"
            parts = full_name.split("/")
            sub_key = (parts[1], parts[3])
            event = self.deliverable_events.get(sub_key)
            if event is not None:
                event.set()

        return pubsub_pb2.PublishResponse(message_ids=message_ids)


class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(
        self,
        *,
        storage: PubSubStorage,
        publisher: PublisherServicer,
    ) -> None:
        self._storage = storage
        self._publisher = publisher  # used to register deliverable events
        self._backlogs: dict[tuple[str, str], SubscriptionBacklog] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def _get_backlog(
        self, project: str, sub_id: str
    ) -> tuple[SubscriptionBacklog, asyncio.Lock]:
        """Lazily create a backlog + lock the first time a subscription is touched."""
        key = (project, sub_id)
        if key not in self._backlogs:
            sub = await self._storage.get_subscription(project, sub_id)
            backlog = SubscriptionBacklog(
                ack_deadline_seconds=sub.ack_deadline_seconds,
                enable_ordering=sub.enable_message_ordering,
            )
            self._backlogs[key] = backlog
            self._locks[key] = asyncio.Lock()
            # Register the deliverable Event with the publisher so Publish wakes us up.
            self._publisher.deliverable_events[key] = backlog.deliverable
        return self._backlogs[key], self._locks[key]

    async def _drop_backlog(self, project: str, sub_id: str) -> None:
        """Called from DeleteSubscription so the backlog is cleaned up."""
        key = (project, sub_id)
        self._backlogs.pop(key, None)
        self._locks.pop(key, None)
        self._publisher.deliverable_events.pop(key, None)

    async def CreateSubscription(
        self,
        request: pubsub_pb2.Subscription,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Subscription:
        try:
            rec = _sub_proto_to_record(request)
            await self._storage.create_subscription(rec)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _sub_record_to_proto(rec)

    async def GetSubscription(
        self,
        request: pubsub_pb2.GetSubscriptionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Subscription:
        try:
            project, sub_id = _parse_subscription(request.subscription)
            rec = await self._storage.get_subscription(project, sub_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _sub_record_to_proto(rec)

    async def UpdateSubscription(
        self,
        request: pubsub_pb2.UpdateSubscriptionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.Subscription:
        try:
            project, sub_id = _parse_subscription(request.subscription.name)
            existing = await self._storage.get_subscription(project, sub_id)
            paths = set(request.update_mask.paths)
            updated = SubscriptionRecord(
                project=existing.project,
                subscription_id=existing.subscription_id,
                topic_project=existing.topic_project,
                topic_id=existing.topic_id,
                ack_deadline_seconds=(
                    request.subscription.ack_deadline_seconds
                    if "ack_deadline_seconds" in paths
                    else existing.ack_deadline_seconds
                ),
                enable_message_ordering=existing.enable_message_ordering,
                push_config=existing.push_config,
                filter=existing.filter,
                dead_letter_policy=existing.dead_letter_policy,
                retry_policy=existing.retry_policy,
                labels=(
                    dict(request.subscription.labels)
                    if "labels" in paths
                    else dict(existing.labels)
                ),
                enable_exactly_once_delivery=existing.enable_exactly_once_delivery,
                create_time=existing.create_time,
            )
            await self._storage.update_subscription(updated)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return _sub_record_to_proto(updated)

    async def DeleteSubscription(
        self,
        request: pubsub_pb2.DeleteSubscriptionRequest,
        context: grpc.aio.ServicerContext,
    ):
        from google.protobuf import empty_pb2

        try:
            project, sub_id = _parse_subscription(request.subscription)
            await self._storage.delete_subscription(project, sub_id)
            await self._drop_backlog(project, sub_id)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)
        return empty_pb2.Empty()

    async def ListSubscriptions(
        self,
        request: pubsub_pb2.ListSubscriptionsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.ListSubscriptionsResponse:
        if not request.project.startswith("projects/"):
            await _abort(context, InvalidArgument(f"Invalid project: {request.project!r}"))
        project = request.project[len("projects/") :]
        try:
            offset = _decode_token(request.page_token)
        except InvalidArgument as e:
            await _abort(context, e)
        page_size = request.page_size or 100
        rows = sorted(
            await self._storage.list_subscriptions(project),
            key=lambda r: r.subscription_id,
        )
        slice_ = rows[offset : offset + page_size]
        next_token = _encode_token(offset + page_size) if offset + page_size < len(rows) else ""
        return pubsub_pb2.ListSubscriptionsResponse(
            subscriptions=[_sub_record_to_proto(r) for r in slice_],
            next_page_token=next_token,
        )

    async def Pull(
        self,
        request: pubsub_pb2.PullRequest,
        context: grpc.aio.ServicerContext,
    ) -> pubsub_pb2.PullResponse:
        try:
            project, sub_id = _parse_subscription(request.subscription)
            backlog, lock = await self._get_backlog(project, sub_id)
            max_messages = request.max_messages or 1
            topic_proj, topic_id = await self._resolve_topic(project, sub_id)
            # Try once; if empty and !return_immediately, long-poll on the
            # deliverable Event.
            async with lock:
                messages = await self._storage.get_messages(topic_proj, topic_id)
                delivered = await backlog.pull(
                    messages=messages,
                    max_count=max_messages,
                    now=dt.datetime.now(dt.UTC),
                )
            if delivered or request.return_immediately:
                return self._pull_response(delivered)
            # Long-poll: wait up to 90s for a new publish or NACK.
            try:
                backlog.deliverable.clear()
                await asyncio.wait_for(
                    backlog.deliverable.wait(),
                    timeout=_LONG_POLL_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                return self._pull_response([])
            async with lock:
                messages = await self._storage.get_messages(topic_proj, topic_id)
                delivered = await backlog.pull(
                    messages=messages,
                    max_count=max_messages,
                    now=dt.datetime.now(dt.UTC),
                )
            return self._pull_response(delivered)
        except (PubSubError, InvalidName) as e:
            await _abort(context, e)

    async def _resolve_topic(self, project: str, sub_id: str) -> tuple[str, str]:
        """Return the (topic_project, topic_id) pair for a subscription."""
        sub = await self._storage.get_subscription(project, sub_id)
        return sub.topic_project, sub.topic_id

    def _pull_response(self, delivered: list[DeliveredMessage]) -> pubsub_pb2.PullResponse:
        from google.protobuf.timestamp_pb2 import Timestamp

        received: list[pubsub_pb2.ReceivedMessage] = []
        for d in delivered:
            ts = Timestamp()
            ts.FromDatetime(d.message.publish_time)
            received.append(
                pubsub_pb2.ReceivedMessage(
                    ack_id=d.ack_id,
                    message=pubsub_pb2.PubsubMessage(
                        data=d.message.data,
                        attributes=d.message.attributes,
                        message_id=d.message.message_id,
                        publish_time=ts,
                        ordering_key=d.message.ordering_key or "",
                    ),
                )
            )
        return pubsub_pb2.PullResponse(received_messages=received)
