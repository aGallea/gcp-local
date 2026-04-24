import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from gcp_local.cli import Settings, run
from gcp_local.core.registry import ServiceRegistry
from gcp_local.services.gcs import GcsService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"port {port} did not open within {timeout}s")


@pytest_asyncio.fixture
async def emulator(tmp_path: Path) -> AsyncIterator[dict[str, int]]:
    """Boot the emulator in-process with the GCS service on a free port."""
    registry = ServiceRegistry()
    registry.register("gcs", GcsService)

    admin_port = _free_port()
    gcs_port = _free_port()
    settings = Settings(
        services=["gcs"],
        persist=False,
        data_dir=tmp_path,
        admin_port=admin_port,
        port_overrides={"gcs": gcs_port},
    )
    task = asyncio.create_task(run(registry, settings), name="emulator")
    try:
        await _wait_for_port(admin_port)
        await _wait_for_port(gcs_port)
        yield {"admin_port": admin_port, "gcs_port": gcs_port}
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
