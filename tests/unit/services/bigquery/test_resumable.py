"""ResumableSessionStore unit tests (spec §5.2)."""

import pytest

from gcp_local.services.bigquery.engine.resumable import (
    OutOfOrderChunk,
    ResumableSessionNotFound,
    ResumableSessionStore,
)


def test_init_returns_session_id_and_stores_config() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={"sourceFormat": "CSV"}, declared_total=42)
    sess = store.get(sid)
    assert sess.project == "p"
    assert sess.declared_total == 42
    assert sess.received_total == 0


def test_append_completes_when_total_reached() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=10)
    store.append(sid, b"01234", start=0, end=4, total=10)
    assert store.get(sid).received_total == 5
    complete = store.append(sid, b"56789", start=5, end=9, total=10)
    assert complete is True


def test_append_returns_false_until_complete() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=10)
    assert store.append(sid, b"01234", start=0, end=4, total=10) is False


def test_append_out_of_order_raises() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=10)
    with pytest.raises(OutOfOrderChunk):
        store.append(sid, b"56789", start=5, end=9, total=10)


def test_unknown_session_raises() -> None:
    store = ResumableSessionStore()
    with pytest.raises(ResumableSessionNotFound):
        store.get("no-such-session")


def test_drop_removes_session() -> None:
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=None)
    store.drop(sid)
    with pytest.raises(ResumableSessionNotFound):
        store.get(sid)


def test_total_unknown_streams_until_marked() -> None:
    """Client sends Content-Range bytes 0-9/* and later 10-19/20."""
    store = ResumableSessionStore()
    sid = store.init(project="p", job_config={}, declared_total=None)
    assert store.append(sid, b"0123456789", start=0, end=9, total=None) is False
    assert store.append(sid, b"abcdefghij", start=10, end=19, total=20) is True


def test_sweep_expired_drops_old_sessions() -> None:
    store = ResumableSessionStore()
    clock = [100.0]
    store.set_clock(lambda: clock[0])
    sid_old = store.init(project="p", job_config={}, declared_total=None)
    clock[0] = 1000.0  # 900s past sid_old's last_write
    store.sweep_expired(ttl_seconds=600)
    with pytest.raises(ResumableSessionNotFound):
        store.get(sid_old)
    # Fresh session within TTL should survive.
    sid_fresh = store.init(project="p", job_config={}, declared_total=None)
    clock[0] = 1100.0  # 100s past sid_fresh's last_write
    store.sweep_expired(ttl_seconds=600)
    assert store.get(sid_fresh).received_total == 0
