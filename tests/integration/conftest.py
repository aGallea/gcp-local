import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from pathlib import Path

# Import the client libraries *before* gcp_local loads its generated *_pb2
# modules. Both proto-plus (used by google-cloud-{secretmanager,pubsub}) and
# our protoc-generated pb2 files register the same fully-qualified symbols
# into the default protobuf descriptor pool. Whichever arrives second wins
# the registration race — but proto-plus calls ``pool.Add`` directly (no
# fallback), while our pb2 files were patched (in scripts/gen_protos.sh) to
# wrap ``AddSerializedFile`` in a ``try/except`` falling back to
# ``FindFileContainingSymbol``. So: client libraries must load first, our
# pb2 modules second.
import google.cloud.firestore_v1
import google.cloud.pubsub_v1
import google.cloud.secretmanager_v1  # noqa: F401
import pytest_asyncio

from gcp_local.cli import Settings, run
from gcp_local.core.registry import ServiceRegistry
from gcp_local.services.bigquery import BigQueryService
from gcp_local.services.firestore import FirestoreService
from gcp_local.services.gcs import GcsService
from gcp_local.services.metadata import MetadataService
from gcp_local.services.pubsub import PubSubService
from gcp_local.services.secret_manager import SecretManagerService


def _bound_socket() -> socket.socket:
    """Return a TCP socket bound to 0.0.0.0:0, kept open to hold the port.

    The caller passes this socket directly to the service (uvicorn uses it via
    serve(sockets=[s]); gRPC services close it just before binding). Holding
    the socket open until the service is ready eliminates the TOCTOU race
    where the OS could hand the port to another process in the gap between
    _free_port() releasing it and the service re-binding it.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))
    return s


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
    """Boot the emulator in-process with gcs + secret_manager + bigquery + pubsub + firestore on free ports."""
    registry = ServiceRegistry()
    registry.register("gcs", GcsService)
    registry.register("secret_manager", SecretManagerService)
    registry.register("bigquery", BigQueryService)
    registry.register("pubsub", PubSubService)
    registry.register("firestore", FirestoreService)
    registry.register("metadata", MetadataService)

    admin_sock = _bound_socket()
    gcs_sock = _bound_socket()
    secret_manager_sock = _bound_socket()
    bigquery_sock = _bound_socket()
    pubsub_sock = _bound_socket()
    firestore_sock = _bound_socket()
    metadata_sock = _bound_socket()

    admin_port = admin_sock.getsockname()[1]
    gcs_port = gcs_sock.getsockname()[1]
    secret_manager_port = secret_manager_sock.getsockname()[1]
    bigquery_port = bigquery_sock.getsockname()[1]
    pubsub_port = pubsub_sock.getsockname()[1]
    firestore_port = firestore_sock.getsockname()[1]
    metadata_port = metadata_sock.getsockname()[1]

    settings = Settings(
        services=["gcs", "secret_manager", "bigquery", "pubsub", "firestore", "metadata"],
        persist=False,
        data_dir=tmp_path,
        admin_port=admin_port,
        port_overrides={
            "gcs": gcs_port,
            "secret_manager": secret_manager_port,
            "bigquery": bigquery_port,
            "pubsub": pubsub_port,
            "firestore": firestore_port,
            "metadata": metadata_port,
        },
    )
    sockets = {
        "admin": admin_sock,
        "gcs": gcs_sock,
        "secret_manager": secret_manager_sock,
        "bigquery": bigquery_sock,
        "pubsub": pubsub_sock,
        "firestore": firestore_sock,
        "metadata": metadata_sock,
    }
    task = asyncio.create_task(run(registry, settings, sockets=sockets), name="emulator")
    try:
        await _wait_for_port(admin_port)
        await _wait_for_port(gcs_port)
        await _wait_for_port(secret_manager_port)
        await _wait_for_port(bigquery_port)
        await _wait_for_port(pubsub_port)
        await _wait_for_port(firestore_port)
        await _wait_for_port(metadata_port)
        yield {
            "admin_port": admin_port,
            "gcs_port": gcs_port,
            "secret_manager_port": secret_manager_port,
            "bigquery_port": bigquery_port,
            "pubsub_port": pubsub_port,
            "firestore_port": firestore_port,
            "metadata_port": metadata_port,
        }
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


@pytest_asyncio.fixture
async def emulator_endpoints(emulator: dict[str, int]) -> dict[str, str]:
    """Map service name -> "host:port" string, for clients that want a single endpoint."""
    return {
        "admin": f"127.0.0.1:{emulator['admin_port']}",
        "gcs": f"127.0.0.1:{emulator['gcs_port']}",
        "secret_manager": f"127.0.0.1:{emulator['secret_manager_port']}",
        "bigquery": f"127.0.0.1:{emulator['bigquery_port']}",
        "pubsub": f"127.0.0.1:{emulator['pubsub_port']}",
        "firestore": f"127.0.0.1:{emulator['firestore_port']}",
        "metadata": f"127.0.0.1:{emulator['metadata_port']}",
    }
