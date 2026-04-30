import grpc
import pytest

from gcp_local.services.pubsub.errors import (
    InvalidArgument,
    PubSubError,
    SubscriptionAlreadyExists,
    SubscriptionNotFound,
    TopicAlreadyExists,
    TopicNotFound,
    grpc_code_for,
)


@pytest.mark.parametrize(
    "exc, expected_code",
    [
        (TopicNotFound("projects/p/topics/t"), grpc.StatusCode.NOT_FOUND),
        (SubscriptionNotFound("projects/p/subscriptions/s"), grpc.StatusCode.NOT_FOUND),
        (TopicAlreadyExists("projects/p/topics/t"), grpc.StatusCode.ALREADY_EXISTS),
        (SubscriptionAlreadyExists("projects/p/subscriptions/s"), grpc.StatusCode.ALREADY_EXISTS),
        (InvalidArgument("bad ack id"), grpc.StatusCode.INVALID_ARGUMENT),
    ],
)
def test_grpc_code_for_known_exceptions(exc: PubSubError, expected_code: grpc.StatusCode) -> None:
    assert grpc_code_for(exc) == expected_code


def test_grpc_code_for_unknown_exception_is_internal() -> None:
    assert grpc_code_for(RuntimeError("boom")) == grpc.StatusCode.INTERNAL
