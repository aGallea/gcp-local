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
