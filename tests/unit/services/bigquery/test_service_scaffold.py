import asyncio
import socket
from pathlib import Path

import httpx
import pytest

from gcp_local.core.context import Context
from gcp_local.core.state_hub import StateHub
from gcp_local.services.bigquery import BigQueryService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_service_starts_and_serves_root(tmp_path: Path) -> None:
    port = _free_port()
    ctx = Context(
        persist=False,
        data_dir=tmp_path,
        port_overrides={"bigquery": port},
        state_hub=StateHub(),
    )
    svc = BigQueryService()
    await svc.start(ctx)
    try:
        # Wait for server to bind.
        for _ in range(50):
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"http://127.0.0.1:{port}/")
                if r.status_code == 200:
                    break
            except httpx.ConnectError:
                await asyncio.sleep(0.05)
        else:
            raise AssertionError("bigquery service did not start")
        assert r.json() == {"service": "bigquery", "status": "ok"}
        assert svc.health().ok is True
    finally:
        await svc.stop()
        assert svc.health().ok is False


def test_service_declares_default_port() -> None:
    svc = BigQueryService()
    assert svc.name == "bigquery"
    assert [p.number for p in svc.default_ports] == [9050]
    assert [p.protocol for p in svc.default_ports] == ["rest"]
