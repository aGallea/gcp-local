from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from gcp_local.core.context import Context

Protocol_ = Literal["rest", "grpc"]


@dataclass(frozen=True)
class Port:
    number: int
    protocol: Protocol_
    # Set on every port after the first, so each one gets its own override key.
    name: str = ""


def port_override_key(service: str, port: Port) -> str:
    return f"{service}_{port.name}" if port.name else service


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
