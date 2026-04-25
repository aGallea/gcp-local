import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from pathlib import Path

# Import the client library *before* gcp_local loads its generated *_pb2 modules.
# Both proto-plus (used by google-cloud-secret-manager) and protoc-generated pb2
# files attempt to register the same fully-qualified symbols into the default
# protobuf descriptor pool; whichever arrives second raises "duplicate symbol".
# Loading the client library first lets our pb2 modules fall back gracefully to
# FindFileContainingSymbol instead of AddSerializedFile.
import google.cloud.secretmanager_v1  # noqa: F401
import pytest_asyncio

from gcp_local.cli import Settings, run
from gcp_local.core.registry import ServiceRegistry
from gcp_local.services.gcs import GcsService
from gcp_local.services.secret_manager import SecretManagerService


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
    """Boot the emulator in-process with gcs + secret_manager on free ports."""
    registry = ServiceRegistry()
    registry.register("gcs", GcsService)
    registry.register("secret_manager", SecretManagerService)

    admin_port = _free_port()
    gcs_port = _free_port()
    secret_manager_port = _free_port()
    settings = Settings(
        services=["gcs", "secret_manager"],
        persist=False,
        data_dir=tmp_path,
        admin_port=admin_port,
        port_overrides={"gcs": gcs_port, "secret_manager": secret_manager_port},
    )
    task = asyncio.create_task(run(registry, settings), name="emulator")
    try:
        await _wait_for_port(admin_port)
        await _wait_for_port(gcs_port)
        await _wait_for_port(secret_manager_port)
        yield {
            "admin_port": admin_port,
            "gcs_port": gcs_port,
            "secret_manager_port": secret_manager_port,
        }
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
