from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    """Marker protocol for per-service storage backends.

    Each service defines its own richer protocol inheriting from this.
    The core only needs to know how to locate on-disk state dirs.
    """


def data_path(service_name: str, base: Path) -> Path:
    """Return (and create) the on-disk directory for a service under `base`."""
    p = base / service_name
    p.mkdir(parents=True, exist_ok=True)
    return p
