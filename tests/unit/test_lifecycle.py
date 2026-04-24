import asyncio
from pathlib import Path

import pytest

from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle, ServiceStartError
from gcp_local.core.service import HealthStatus, Port


class RecordingService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.default_ports = [Port(1, "rest")]
        self.started = False
        self.stopped = False
        self.resets = 0

    async def start(self, ctx):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def reset_state(self):
        self.resets += 1

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self.started)


class FailingStart(RecordingService):
    async def start(self, ctx):
        raise RuntimeError("boom")


def make_ctx(tmp_path: Path) -> Context:
    return Context(persist=False, data_dir=tmp_path)


async def test_start_all_starts_every_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.start_all()
    assert a.started and b.started


async def test_stop_all_stops_every_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.start_all()
    await lc.stop_all()
    assert a.stopped and b.stopped


async def test_start_failure_rolls_back(tmp_path: Path):
    a = RecordingService("a")
    bad = FailingStart("bad")
    lc = Lifecycle([a, bad], make_ctx(tmp_path))
    with pytest.raises(ServiceStartError, match="bad"):
        await lc.start_all()
    # `a` had started, so it must be stopped during rollback
    assert a.stopped is True


async def test_reset_all_resets_every_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.reset_all()
    assert a.resets == 1 and b.resets == 1


async def test_reset_specific_service(tmp_path: Path):
    a, b = RecordingService("a"), RecordingService("b")
    lc = Lifecycle([a, b], make_ctx(tmp_path))
    await lc.reset("b")
    assert a.resets == 0 and b.resets == 1


async def test_reset_unknown_raises(tmp_path: Path):
    a = RecordingService("a")
    lc = Lifecycle([a], make_ctx(tmp_path))
    with pytest.raises(KeyError):
        await lc.reset("nope")
