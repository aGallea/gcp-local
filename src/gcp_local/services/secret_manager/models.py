from dataclasses import dataclass, field
from enum import StrEnum


class SecretVersionState(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DESTROYED = "DESTROYED"


@dataclass
class SecretVersion:
    id: int
    state: SecretVersionState
    create_time: str
    destroy_time: str | None
    payload: bytes
    data_crc32c: int


@dataclass
class SecretRecord:
    project: str
    secret_id: str
    labels: dict[str, str]
    annotations: dict[str, str]
    create_time: str
    versions: list[SecretVersion] = field(default_factory=list)

    def highest_enabled_version(self) -> SecretVersion | None:
        enabled = [v for v in self.versions if v.state == SecretVersionState.ENABLED]
        if not enabled:
            return None
        return max(enabled, key=lambda v: v.id)

    def get_version(self, version_id: int) -> SecretVersion | None:
        for v in self.versions:
            if v.id == version_id:
                return v
        return None
