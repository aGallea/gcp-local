"""Pub/Sub-specific exception types and gRPC code mapping."""

import grpc


class PubSubError(Exception):
    """Base for all Pub/Sub-internal exceptions."""


class TopicNotFound(PubSubError):
    pass


class SubscriptionNotFound(PubSubError):
    pass


class TopicAlreadyExists(PubSubError):
    pass


class SubscriptionAlreadyExists(PubSubError):
    pass


class InvalidArgument(PubSubError):
    """Wire-shape validation failure (bad ack_id, missing required field, etc.)."""


_CODE_MAP: dict[type[Exception], grpc.StatusCode] = {
    TopicNotFound: grpc.StatusCode.NOT_FOUND,
    SubscriptionNotFound: grpc.StatusCode.NOT_FOUND,
    TopicAlreadyExists: grpc.StatusCode.ALREADY_EXISTS,
    SubscriptionAlreadyExists: grpc.StatusCode.ALREADY_EXISTS,
    InvalidArgument: grpc.StatusCode.INVALID_ARGUMENT,
}


def grpc_code_for(exc: Exception) -> grpc.StatusCode:
    return _CODE_MAP.get(type(exc), grpc.StatusCode.INTERNAL)
