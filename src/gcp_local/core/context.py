from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from gcp_local.core.service import Port, port_override_key

if TYPE_CHECKING:
    from gcp_local.core.state_hub import StateHub


@dataclass
class Context:
    persist: bool
    data_dir: Path
    port_overrides: dict[str, int] = field(default_factory=dict)
    state_hub: "StateHub | None" = None

    def port_for(self, service: str, port: Port) -> int:
        return self.port_overrides.get(port_override_key(service, port), port.number)
