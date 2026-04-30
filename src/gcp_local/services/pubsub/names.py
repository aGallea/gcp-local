"""Pub/Sub resource-name parsing & validation.

Matches the official Pub/Sub naming rules: 3-255 chars, must start with
a letter, may not start with the literal 'goog' (case-insensitive),
allowed character class is letters/digits/'-_.~+%'. The validator is
shared by topic and subscription IDs (the rules are identical).
"""

import re

_RE_TOPIC = re.compile(r"^projects/([^/]+)/topics/([^/]+)$")
_RE_SUBSCRIPTION = re.compile(r"^projects/([^/]+)/subscriptions/([^/]+)$")
_RE_VALID_ID = re.compile(r"^[A-Za-z][A-Za-z0-9\-_.~+%]{2,254}$")


class InvalidName(ValueError):
    """Resource name does not match Pub/Sub naming rules."""


def parse_topic_name(name: str) -> tuple[str, str]:
    m = _RE_TOPIC.fullmatch(name)
    if not m:
        raise InvalidName(f"Invalid topic name: {name!r}")
    return m.group(1), m.group(2)


def build_topic_name(project: str, topic_id: str) -> str:
    return f"projects/{project}/topics/{topic_id}"


def parse_subscription_name(name: str) -> tuple[str, str]:
    m = _RE_SUBSCRIPTION.fullmatch(name)
    if not m:
        raise InvalidName(f"Invalid subscription name: {name!r}")
    return m.group(1), m.group(2)


def build_subscription_name(project: str, subscription_id: str) -> str:
    return f"projects/{project}/subscriptions/{subscription_id}"


def validate_resource_id(rid: str) -> None:
    if not _RE_VALID_ID.fullmatch(rid):
        raise InvalidName(f"Invalid resource id: {rid!r}")
    if rid.lower().startswith("goog"):
        raise InvalidName(f"Resource id may not start with 'goog': {rid!r}")
