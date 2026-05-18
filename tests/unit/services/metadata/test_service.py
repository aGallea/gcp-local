"""Lifecycle / wiring tests for MetadataService."""

import asyncio
import socket
from pathlib import Path

import httpx
import pytest

from gcp_local.core.context import Context
from gcp_local.core.registry import ServiceRegistry
from gcp_local.services.metadata import MetadataService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        sockaddr = s.getsockname()
        return int(sockaddr[1])


async def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.02)
    raise TimeoutError(f"port {port} did not open within {timeout}s")


def test_metadata_service_is_discovered_via_entry_points() -> None:
    registry = ServiceRegistry()
    registry.discover_from_entry_points()
    assert "metadata" in registry.names()


def test_metadata_service_is_included_in_default_all_selection() -> None:
    registry = ServiceRegistry()
    registry.discover_from_entry_points()
    assert "metadata" in registry.resolve_selection("all")


@pytest.mark.asyncio
async def test_service_start_binds_port_and_serves_requests(tmp_path: Path) -> None:
    port = _free_port()
    svc = MetadataService()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"metadata": port})
    await svc.start(ctx)
    try:
        await _wait_for_port(port)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            resp = await client.get(
                "/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
            assert resp.status_code == 200
            assert resp.text == "local-dev"
    finally:
        await svc.stop()


@pytest.mark.asyncio
async def test_service_health_reflects_lifecycle(tmp_path: Path) -> None:
    svc = MetadataService()
    assert svc.health().ok is False
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"metadata": _free_port()})
    await svc.start(ctx)
    try:
        assert svc.health().ok is True
    finally:
        await svc.stop()
    assert svc.health().ok is False


@pytest.mark.asyncio
async def test_service_reset_state_is_a_noop(tmp_path: Path) -> None:
    svc = MetadataService()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"metadata": _free_port()})
    await svc.start(ctx)
    try:
        await _wait_for_port(ctx.port_overrides["metadata"])
        await svc.reset_state()  # must not raise
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{ctx.port_overrides['metadata']}"
        ) as client:
            resp = await client.get(
                "/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
            assert resp.status_code == 200
    finally:
        await svc.stop()
