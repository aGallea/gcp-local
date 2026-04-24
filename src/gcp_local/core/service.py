from dataclasses import dataclass
from typing import Literal, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from gcp_local.core.context import Context

Protocol_ = Literal["rest", "grpc"]


@dataclass(frozen=True)
class Port:
    number: int
    protocol: Protocol_


@dataclass
class HealthStatus:
    ok: bool
    message: str = ""


@runtime_checkable
class Service(Protocol):
    name: str
    default_ports: list[Port]

    async def start(self, ctx: "Context") -> None: ...
    async def stop(self) -> None: ...
    async def reset_state(self) -> None: ...
    def health(self) -> HealthStatus: ...
