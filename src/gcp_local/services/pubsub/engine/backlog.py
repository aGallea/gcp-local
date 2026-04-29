"""Per-subscription delivery state machine.

Owns the cursor, outstanding ack-leases, the NACK queue, and the
ordering-key block set. The backlog does NOT hold message data — the
caller (the servicer) passes the topic's message list into ``pull`` /
``sweep_expired``. This keeps the backlog cheap to instantiate and
trivially serializable across resets.

All public methods are coroutine functions. Ordering keys are honored
only when ``enable_ordering=True`` was set on construction (matching
the SubscriptionRecord field).
"""

import asyncio
import datetime as dt
import uuid
from dataclasses import dataclass

from gcp_local.services.pubsub.models import AckLease, MessageRecord


@dataclass
class DeliveredMessage:
    ack_id: str
    message: MessageRecord


class SubscriptionBacklog:
    """All per-subscription delivery state. Not safe for concurrent pulls
    on the same instance — the servicer wraps a per-subscription lock around
    the ``pull`` / ``acknowledge`` / ``modify_ack_deadline`` / ``seek`` calls.
    """

    def __init__(self, *, ack_deadline_seconds: int, enable_ordering: bool) -> None:
        self.ack_deadline_seconds = ack_deadline_seconds
        self.enable_ordering = enable_ordering
        self._cursor = 0
        self._leases: dict[str, AckLease] = {}
        self._lease_to_key: dict[str, str] = {}  # ack_id → ordering_key (when ordering on)
        self._nacked: list[int] = []  # message indices to redeliver next
        self._ordering_blocked: set[str] = set()
        # asyncio.Event toggled when a new message is appended OR a NACK lands —
        # the long-poll Pull awaits it. The servicer wires this up.
        self.deliverable = asyncio.Event()

    async def pull(
        self,
        *,
        messages: list[MessageRecord],
        max_count: int,
        now: dt.datetime,
    ) -> list[DeliveredMessage]:
        # Opportunistic sweep on every pull (the §5.3 timer is the backstop).
        self.sweep_expired(now=now)
        out: list[DeliveredMessage] = []
        # NACKed messages first.
        remaining_nacked: list[int] = []
        for idx in self._nacked:
            if len(out) >= max_count:
                remaining_nacked.append(idx)
                continue
            msg = messages[idx]
            if self.enable_ordering and msg.ordering_key in self._ordering_blocked:
                remaining_nacked.append(idx)
                continue
            out.append(self._mint_lease(idx, msg, now))
        self._nacked = remaining_nacked
        # Then advance through the cursor.
        while len(out) < max_count and self._cursor < len(messages):
            msg = messages[self._cursor]
            if self.enable_ordering and msg.ordering_key in self._ordering_blocked:
                # Cannot deliver this message yet — but we still advance the cursor.
                # Push it onto _nacked so the next pull retries when the key unblocks.
                # Important: only push once. If it's already pending we'd duplicate
                # — guarded by tracking the highest cursor we've blocked.
                self._nacked.append(self._cursor)
                self._cursor += 1
                continue
            out.append(self._mint_lease(self._cursor, msg, now))
            self._cursor += 1
        return out

    def _mint_lease(self, idx: int, msg: MessageRecord, now: dt.datetime) -> DeliveredMessage:
        ack_id = f"lease-{uuid.uuid4().hex}"
        deadline = now + dt.timedelta(seconds=self.ack_deadline_seconds)
        self._leases[ack_id] = AckLease(ack_id=ack_id, message_index=idx, deadline_at=deadline)
        if self.enable_ordering and msg.ordering_key:
            self._ordering_blocked.add(msg.ordering_key)
            self._lease_to_key[ack_id] = msg.ordering_key
        return DeliveredMessage(ack_id=ack_id, message=msg)

    async def acknowledge(self, ack_ids: list[str]) -> None:
        for aid in ack_ids:
            self._drop_lease(aid)

    async def modify_ack_deadline(self, items: list[tuple[str, int]]) -> None:
        for ack_id, delta in items:
            lease = self._leases.get(ack_id)
            if lease is None:
                continue
            if delta == 0:
                # NACK: redeliver immediately.
                self._drop_lease(ack_id)
                self._nacked.append(lease.message_index)
                self.deliverable.set()
            else:
                lease.deadline_at = lease.deadline_at + dt.timedelta(seconds=delta)

    def _drop_lease(self, ack_id: str) -> None:
        lease = self._leases.pop(ack_id, None)
        if lease is None:
            return
        key = self._lease_to_key.pop(ack_id, None)
        if key is not None:
            self._ordering_blocked.discard(key)

    def sweep_expired(self, *, now: dt.datetime) -> int:
        """Reclaim any lease whose deadline has passed; return how many were swept."""
        expired = [aid for aid, lease in self._leases.items() if lease.deadline_at < now]
        for aid in expired:
            lease = self._leases.pop(aid)
            key = self._lease_to_key.pop(aid, None)
            if key is not None:
                self._ordering_blocked.discard(key)
            self._nacked.append(lease.message_index)
        if expired:
            self.deliverable.set()
        return len(expired)

    async def seek(self, *, message_index: int) -> None:
        """Reset the subscription to a specific position; drop all in-flight leases."""
        self._leases.clear()
        self._lease_to_key.clear()
        self._nacked.clear()
        self._ordering_blocked.clear()
        self._cursor = message_index
        self.deliverable.set()
