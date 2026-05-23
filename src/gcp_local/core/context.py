import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_local.core.state_hub import StateHub


@dataclass
class Context:
    persist: bool
    data_dir: Path
    port_overrides: dict[str, int] = field(default_factory=dict)
    state_hub: "StateHub | None" = None
    # Pre-bound sockets keyed by service name. When present, the service uses
    # the socket directly instead of binding a fresh one, eliminating the
    # TOCTOU gap between port allocation and service bind.
    sockets: dict[str, "socket.socket"] = field(default_factory=dict)
