"""In-memory resumable-upload session store (spec §5.2)."""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ResumableSessionNotFound(KeyError):
    pass


class OutOfOrderChunk(ValueError):
    pass


@dataclass
class ResumableUpload:
    session_id: str
    project: str
    job_config: dict[str, Any]
    declared_total: int | None
    received_total: int = 0
    chunks: bytearray = field(default_factory=bytearray)
    last_write: float = 0.0


class ResumableSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ResumableUpload] = {}
        self._clock: Callable[[], float] = time.monotonic

    def set_clock(self, clock: Callable[[], float]) -> None:
        self._clock = clock

    def init(
        self,
        *,
        project: str,
        job_config: dict[str, Any],
        declared_total: int | None,
    ) -> str:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = ResumableUpload(
            session_id=session_id,
            project=project,
            job_config=job_config,
            declared_total=declared_total,
            last_write=self._clock(),
        )
        return session_id

    def get(self, session_id: str) -> ResumableUpload:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise ResumableSessionNotFound(session_id) from None

    def append(
        self,
        session_id: str,
        chunk: bytes,
        *,
        start: int,
        end: int,
        total: int | None,
    ) -> bool:
        """Append a chunk; return True if the upload is now complete."""
        sess = self.get(session_id)
        if start != sess.received_total:
            raise OutOfOrderChunk(
                f"expected start={sess.received_total}, got {start}"
            )
        sess.chunks.extend(chunk)
        sess.received_total = end + 1
        sess.last_write = self._clock()
        if total is not None:
            sess.declared_total = total
            return sess.received_total == total
        return False

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def sweep_expired(self, ttl_seconds: float) -> None:
        now = self._clock()
        expired = [
            sid
            for sid, sess in self._sessions.items()
            if (now - sess.last_write) > ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
