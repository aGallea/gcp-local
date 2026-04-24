import base64
import hashlib
import secrets
import struct
import threading
from datetime import UTC, datetime

import google_crc32c


class GenerationCounter:
    """Monotonic per-bucket generation counter.

    Thread-safe via a lock (cheap, uncontended in the single-loop case).
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def next(self, bucket: str) -> int:
        with self._lock:
            new_val = self._counts.get(bucket, 0) + 1
            self._counts[bucket] = new_val
            return new_val

    def reset_bucket(self, bucket: str) -> None:
        with self._lock:
            self._counts.pop(bucket, None)

    def reset_all(self) -> None:
        with self._lock:
            self._counts.clear()


def new_session_id() -> str:
    """URL-safe 128-bit random token for resumable upload session ids."""
    return secrets.token_urlsafe(16)


def compute_md5_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


def compute_crc32c_b64(data: bytes) -> str:
    checksum = google_crc32c.value(data)
    return base64.b64encode(struct.pack(">I", checksum)).decode("ascii")


def rfc3339_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
