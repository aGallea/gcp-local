"""Lifecycle / wiring tests for SecretManagerService, including socket passing."""

import socket
from pathlib import Path

from gcp_local.core.context import Context
from gcp_local.services.secret_manager.service import SecretManagerService


async def test_pre_bound_socket_is_closed_before_grpc_binds(tmp_path: Path) -> None:
    """When ctx.sockets["secret_manager"] is provided, the service closes it before
    gRPC calls add_insecure_port so the port is handed off with minimal gap."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))

    svc = SecretManagerService()
    ctx = Context(persist=False, data_dir=tmp_path, sockets={"secret_manager": s})
    await svc.start(ctx)
    try:
        assert s.fileno() == -1, "socket must be closed by the service before gRPC binds"
        assert svc.health().ok is True
    finally:
        await svc.stop()


async def test_no_socket_falls_back_to_port_override(tmp_path: Path) -> None:
    """Without ctx.sockets the service uses port_overrides as before."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))
    port = s.getsockname()[1]
    s.close()

    svc = SecretManagerService()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"secret_manager": port})
    await svc.start(ctx)
    try:
        assert svc.health().ok is True
    finally:
        await svc.stop()
