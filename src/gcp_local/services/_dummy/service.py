from typing import ClassVar

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port


class DummyService:
    """Minimal Service implementation used only to exercise the core framework.

    Will be removed once the first real GCP service lands.
    """

    name = "dummy"
    default_ports: ClassVar[list[Port]] = [Port(4599, "rest")]

    def __init__(self) -> None:
        self._started = False
        self._resets = 0

    async def start(self, ctx: Context) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def reset_state(self) -> None:
        self._resets += 1

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self._started,
            message=f"resets={self._resets}",
        )
