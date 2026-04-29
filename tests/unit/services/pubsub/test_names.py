import pytest

from gcp_local.services.pubsub.names import (
    InvalidName,
    build_subscription_name,
    build_topic_name,
    parse_subscription_name,
    parse_topic_name,
    validate_resource_id,
)


def test_parse_topic_name_happy() -> None:
    assert parse_topic_name("projects/my-proj/topics/my-topic") == ("my-proj", "my-topic")


def test_parse_topic_name_rejects_garbage() -> None:
    with pytest.raises(InvalidName):
        parse_topic_name("not/a/valid/path")


def test_build_topic_name() -> None:
    assert build_topic_name("p", "t") == "projects/p/topics/t"


def test_parse_subscription_name_happy() -> None:
    assert parse_subscription_name("projects/p/subscriptions/s") == ("p", "s")


def test_build_subscription_name() -> None:
    assert build_subscription_name("p", "s") == "projects/p/subscriptions/s"


@pytest.mark.parametrize(
    "name",
    ["top", "t-name", "t.name", "t_name", "Name123", "with~plus+pct%20"],
)
def test_validate_resource_id_accepts(name: str) -> None:
    validate_resource_id(name)  # does not raise


@pytest.mark.parametrize(
    "name",
    ["", "ab", "1starts-with-digit", "goog-prefixed", "has spaces", "bad/slash", "x" * 256],
)
def test_validate_resource_id_rejects(name: str) -> None:
    with pytest.raises(InvalidName):
        validate_resource_id(name)
