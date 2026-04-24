import asyncio
import logging

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Service

log = logging.getLogger(__name__)


class ServiceStartError(RuntimeError):
    """Raised when a service fails to start. The rest of the stack has been rolled back."""


class Lifecycle:
    """Orchestrates concurrent start/stop of a fixed set of service instances."""

    def __init__(self, services: list[Service], ctx: Context) -> None:
        self.services = services
        self.ctx = ctx
        self._started: list[Service] = []

    def _by_name(self, name: str) -> Service:
        for s in self.services:
            if s.name == name:
                return s
        raise KeyError(name)

    async def start_all(self) -> None:
        # Start serially so rollback on failure is unambiguous.
        for svc in self.services:
            try:
                await svc.start(self.ctx)
            except Exception as e:
                log.exception("service %s failed to start", svc.name)
                await self._rollback()
                raise ServiceStartError(f"{svc.name}: {e}") from e
            self._started.append(svc)

    async def _rollback(self) -> None:
        for svc in reversed(self._started):
            try:
                await svc.stop()
            except Exception:
                log.exception("service %s failed to stop during rollback", svc.name)
        self._started.clear()

    async def stop_all(self) -> None:
        for svc in reversed(self._started):
            try:
                await svc.stop()
            except Exception:
                log.exception("service %s failed to stop", svc.name)
        self._started.clear()

    async def reset_all(self) -> None:
        await asyncio.gather(*(s.reset_state() for s in self.services))

    async def reset(self, name: str) -> None:
        await self._by_name(name).reset_state()

    def health_all(self) -> dict[str, HealthStatus]:
        return {s.name: s.health() for s in self.services}
