"""StreamingPull session state — flow-control budget tracking.

A ``FlowControl`` instance tracks the outstanding-message / outstanding-byte
budget for a single ``StreamingPull`` session. The values mirror the
``StreamingPullRequest`` flow-control fields: ``0`` means *unlimited*, in
keeping with the public Pub/Sub semantics.
"""

from dataclasses import dataclass


@dataclass
class FlowControl:
    """Per-stream message + bytes budget. ``0`` means unlimited."""

    max_outstanding_messages: int  # 0 = unlimited
    max_outstanding_bytes: int  # 0 = unlimited
    in_flight_messages: int = 0
    in_flight_bytes: int = 0

    def can_yield(self, msg_size: int) -> bool:
        if (
            self.max_outstanding_messages
            and self.in_flight_messages >= self.max_outstanding_messages
        ):
            return False
        return not (
            self.max_outstanding_bytes
            and self.in_flight_bytes + msg_size > self.max_outstanding_bytes
        )

    def on_yield(self, msg_size: int) -> None:
        self.in_flight_messages += 1
        self.in_flight_bytes += msg_size

    def on_ack(self, msg_size: int) -> None:
        self.in_flight_messages = max(0, self.in_flight_messages - 1)
        self.in_flight_bytes = max(0, self.in_flight_bytes - msg_size)
