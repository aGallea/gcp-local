"""Domain dataclasses for the Pub/Sub emulator.

These are the pure in-memory representations; the gRPC servicer
(``servicer.py``) converts to/from the proto messages defined in
``gcp_local.generated.google.pubsub.v1.pubsub_pb2``.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any


@dataclass
class TopicRecord:
    project: str
    topic_id: str
    labels: dict[str, str]
    message_storage_policy: dict[str, Any] | None
    kms_key_name: str | None
    schema_settings: dict[str, Any] | None


@dataclass
class MessageRecord:
    message_id: str
    publish_time: dt.datetime
    data: bytes
    attributes: dict[str, str]
    ordering_key: str  # "" if unset


@dataclass
class SubscriptionRecord:
    project: str
    subscription_id: str
    topic_project: str
    topic_id: str
    ack_deadline_seconds: int
    enable_message_ordering: bool
    push_config: dict[str, Any] | None
    filter: str
    dead_letter_policy: dict[str, Any] | None
    retry_policy: dict[str, Any] | None
    labels: dict[str, str]
    enable_exactly_once_delivery: bool
    create_time: dt.datetime


@dataclass
class AckLease:
    """An in-flight delivery — message returned to a subscriber but not yet acked.

    ``message_index`` is the position into ``PubSubStorage.topic_messages[(p,t)]``;
    leases never reference a MessageRecord by identity, only by index, so leases
    survive arbitrary list growth on the topic side.
    """

    ack_id: str
    message_index: int
    deadline_at: dt.datetime
