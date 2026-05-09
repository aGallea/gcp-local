import asyncio
import contextlib
import logging
import os
import signal
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from gcp_local.core.admin_api import build_admin_app
from gcp_local.core.context import Context
from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.registry import ServiceRegistry
from gcp_local.core.state_hub import StateHub

log = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class Settings:
    services: list[str]
    persist: bool
    data_dir: Path
    admin_port: int
    port_overrides: dict[str, int]


def build_settings(
    env: Mapping[str, str],
    registry: ServiceRegistry,
    default_data_dir: Path,
) -> Settings:
    selection = env.get("SERVICES", "all")
    services = registry.resolve_selection(selection)
    persist = env.get("PERSIST", "").strip().lower() in _TRUTHY
    data_dir = Path(env.get("GCP_LOCAL_DATA_DIR") or default_data_dir)
    admin_port = int(env.get("GCP_LOCAL_ADMIN_PORT", "4510"))

    port_overrides: dict[str, int] = {}
    for name in registry.names():
        key = f"{name.upper()}_EMULATOR_PORT"
        if key in env and env[key].strip():
            port_overrides[name] = int(env[key])

    return Settings(
        services=services,
        persist=persist,
        data_dir=data_dir,
        admin_port=admin_port,
        port_overrides=port_overrides,
    )


async def run(registry: ServiceRegistry, settings: Settings) -> int:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    hub = StateHub()
    ctx = Context(
        persist=settings.persist,
        data_dir=settings.data_dir,
        port_overrides=settings.port_overrides,
        state_hub=hub,
    )
    services = [registry.get(n)() for n in settings.services]
    lc = Lifecycle(services, ctx)

    log.info("starting services: %s", ", ".join(settings.services) or "(none)")
    await lc.start_all()

    admin = build_admin_app(lc)
    admin_server = uvicorn.Server(
        uvicorn.Config(
            admin,
            host="0.0.0.0",
            port=settings.admin_port,
            log_level="info",
            access_log=False,
        )
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows CI
            loop.add_signal_handler(sig, stop_event.set)

    admin_task = asyncio.create_task(admin_server.serve(), name="admin")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop")
    try:
        await asyncio.wait({admin_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        admin_server.should_exit = True
        for t in (admin_task, stop_task):
            if not t.done():
                t.cancel()
        await asyncio.gather(admin_task, stop_task, return_exceptions=True)
        await lc.stop_all()
    return 0


def entrypoint() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    registry = ServiceRegistry()
    registry.discover_from_entry_points()
    settings = build_settings(
        env=os.environ,
        registry=registry,
        default_data_dir=Path.cwd() / ".gcp-local-data",
    )
    sys.exit(asyncio.run(run(registry, settings)))


if __name__ == "__main__":
    entrypoint()
