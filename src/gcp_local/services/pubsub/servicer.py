"""Pub/Sub gRPC servicers."""

import base64
from typing import NoReturn

import grpc

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2, pubsub_pb2_grpc
from gcp_local.services.pubsub.errors import (
    InvalidArgument,
    PubSubError,
    grpc_code_for,
)
from gcp_local.services.pubsub.models import TopicRecord
from gcp_local.services.pubsub.names import (
    InvalidName,
    parse_topic_name,
    validate_resource_id,
)
from gcp_local.services.pubsub.storage import PubSubStorage


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


class PublisherServicer(pubsub_pb2_grpc.PublisherServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage

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


class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage
