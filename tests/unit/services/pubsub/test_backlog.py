import datetime as dt

import pytest

from gcp_local.services.pubsub.engine.backlog import SubscriptionBacklog
from gcp_local.services.pubsub.models import MessageRecord


def _msg(idx: int, *, key: str = "") -> MessageRecord:
    return MessageRecord(
        message_id=f"t-{idx}",
        publish_time=dt.datetime(2026, 4, 29, 12, 0, idx, tzinfo=dt.UTC),
        data=f"m{idx}".encode(),
        attributes={},
        ordering_key=key,
    )


@pytest.mark.asyncio
async def test_pull_with_empty_backlog_returns_nothing() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    out = await b.pull(messages=[], max_count=5, now=dt.datetime(2026, 4, 29, tzinfo=dt.UTC))
    assert out == []


@pytest.mark.asyncio
async def test_pull_advances_cursor_and_mints_lease() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0), _msg(1)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    out = await b.pull(messages=msgs, max_count=2, now=now)
    assert [r.message.message_id for r in out] == ["t-0", "t-1"]
    assert all(r.ack_id.startswith("lease-") for r in out)
    # Pulling again with same backlog returns empty until ack/expire
    assert await b.pull(messages=msgs, max_count=2, now=now) == []


@pytest.mark.asyncio
async def test_acknowledge_drops_lease_permanently() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [r] = await b.pull(messages=msgs, max_count=1, now=now)
    await b.acknowledge([r.ack_id])
    # Even past deadline, acked message does not redeliver
    later = now + dt.timedelta(seconds=20)
    assert await b.pull(messages=msgs, max_count=1, now=later) == []


@pytest.mark.asyncio
async def test_modack_zero_redelivers_immediately() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [r] = await b.pull(messages=msgs, max_count=1, now=now)
    await b.modify_ack_deadline([(r.ack_id, 0)])
    [r2] = await b.pull(messages=msgs, max_count=1, now=now)
    assert r2.message.message_id == "t-0"
    assert r2.ack_id != r.ack_id  # new lease


@pytest.mark.asyncio
async def test_modack_extension_postpones_redelivery() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [r] = await b.pull(messages=msgs, max_count=1, now=now)
    # Extend by 60s — sweep at now+30s should NOT redeliver
    await b.modify_ack_deadline([(r.ack_id, 60)])
    b.sweep_expired(now=now + dt.timedelta(seconds=30))
    assert await b.pull(messages=msgs, max_count=1, now=now + dt.timedelta(seconds=30)) == []


@pytest.mark.asyncio
async def test_sweep_expired_redelivers_after_deadline() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [_r] = await b.pull(messages=msgs, max_count=1, now=now)
    # Deadline at now+10. Sweep at now+11 should reclaim it.
    b.sweep_expired(now=now + dt.timedelta(seconds=11))
    [r2] = await b.pull(messages=msgs, max_count=1, now=now + dt.timedelta(seconds=11))
    assert r2.message.message_id == "t-0"


@pytest.mark.asyncio
async def test_ordering_blocks_same_key_until_ack() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=True)
    msgs = [_msg(0, key="k"), _msg(1, key="k"), _msg(2, key="other")]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    out = await b.pull(messages=msgs, max_count=10, now=now)
    # Should deliver msg0 (first 'k') and msg2 ('other'), but skip msg1 (second 'k').
    assert sorted(r.message.message_id for r in out) == ["t-0", "t-2"]
    # Ack msg0 — now msg1 unblocks.
    ack0 = next(r.ack_id for r in out if r.message.message_id == "t-0")
    await b.acknowledge([ack0])
    [r1] = await b.pull(messages=msgs, max_count=10, now=now)
    assert r1.message.message_id == "t-1"


@pytest.mark.asyncio
async def test_ordering_disabled_ignores_keys() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0, key="k"), _msg(1, key="k")]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    out = await b.pull(messages=msgs, max_count=10, now=now)
    assert [r.message.message_id for r in out] == ["t-0", "t-1"]


@pytest.mark.asyncio
async def test_seek_to_index_clears_state_and_resets_cursor() -> None:
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    msgs = [_msg(0), _msg(1), _msg(2)]
    now = dt.datetime(2026, 4, 29, tzinfo=dt.UTC)
    [_, _] = await b.pull(messages=msgs, max_count=2, now=now)
    await b.seek(message_index=2)
    out = await b.pull(messages=msgs, max_count=10, now=now)
    assert [r.message.message_id for r in out] == ["t-2"]


@pytest.mark.asyncio
async def test_unknown_ack_id_is_ignored_not_raised() -> None:
    """Real Pub/Sub silently ignores unknown ack_ids in Acknowledge / ModifyAckDeadline."""
    b = SubscriptionBacklog(ack_deadline_seconds=10, enable_ordering=False)
    await b.acknowledge(["not-a-real-lease"])  # should not raise
    await b.modify_ack_deadline([("not-a-real-lease", 0)])  # should not raise
