import datetime as dt

from gcp_local.services.pubsub.models import (
    AckLease,
    MessageRecord,
    SubscriptionRecord,
    TopicRecord,
)


def test_topic_record_minimal() -> None:
    t = TopicRecord(
        project="p",
        topic_id="t",
        labels={},
        message_storage_policy=None,
        kms_key_name=None,
        schema_settings=None,
    )
    assert t.project == "p"
    assert t.topic_id == "t"


def test_message_record_holds_attrs_and_data() -> None:
    m = MessageRecord(
        message_id="t-1",
        publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=b"hello",
        attributes={"k": "v"},
        ordering_key="",
    )
    assert m.data == b"hello"
    assert m.attributes == {"k": "v"}
    assert m.ordering_key == ""


def test_subscription_record_defaults_capture_protocol_fields() -> None:
    s = SubscriptionRecord(
        project="p",
        subscription_id="s",
        topic_project="p",
        topic_id="t",
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
    assert s.ack_deadline_seconds == 10


def test_ack_lease_holds_deadline() -> None:
    deadline = dt.datetime(2026, 4, 29, 12, 0, 30, tzinfo=dt.UTC)
    lease = AckLease(ack_id="lease-abc", message_index=42, deadline_at=deadline)
    assert lease.ack_id == "lease-abc"
    assert lease.message_index == 42
    assert lease.deadline_at == deadline
