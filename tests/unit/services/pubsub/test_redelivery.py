"""Tests for the redelivery sweeper task."""

import asyncio
import datetime as dt

import pytest

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
from gcp_local.services.pubsub.engine.delivery import RedeliverySweeper
from gcp_local.services.pubsub.models import MessageRecord


def _msg(idx: int) -> MessageRecord:
    return MessageRecord(
        message_id=f"m-{idx}",
        publish_time=dt.datetime(2026, 4, 29, tzinfo=dt.UTC),
        data=f"d{idx}".encode(),
        attributes={},
        ordering_key="",
    )


@pytest.mark.asyncio
async def test_sweeper_reclaims_expired_leases() -> None:
    backlog = SubscriptionBacklog(
        ack_deadline_seconds=0, enable_ordering=False
    )  # 0s = immediately expired
    [d] = await backlog.pull(messages=[_msg(0)], max_count=1, now=dt.datetime.now(dt.UTC))
    # Lease deadline already in the past; sweeper should NACK it.
    sweeper = RedeliverySweeper(
        backlogs={("p", "s"): backlog},
        tick_interval=0.05,
    )
    await sweeper.start()
    try:
        # Wait long enough for at least 1 tick.
        await asyncio.sleep(0.15)
    finally:
        await sweeper.stop()
    # The previously leased message should now be redeliverable.
    [d2] = await backlog.pull(messages=[_msg(0)], max_count=1, now=dt.datetime.now(dt.UTC))
    assert d2.message.message_id == "m-0"
    assert d2.ack_id != d.ack_id


@pytest.mark.asyncio
async def test_sweeper_idle_when_no_leases() -> None:
    """The sweeper should not raise on subscriptions with empty leases."""
    backlog = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    sweeper = RedeliverySweeper(
        backlogs={("p", "s"): backlog},
        tick_interval=0.05,
    )
    await sweeper.start()
    await asyncio.sleep(0.15)
    await sweeper.stop()
