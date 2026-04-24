from pathlib import Path

import pytest

from gcp_local.cli import Settings, build_settings
from gcp_local.core.registry import ServiceRegistry, UnknownServiceError
from gcp_local.core.service import HealthStatus, Port


class Svc:
    name = ""
    default_ports = [Port(1, "rest")]
    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True)


def make_registry() -> ServiceRegistry:
    r = ServiceRegistry()
    for name in ("gcs", "bigquery"):
        cls = type(f"{name}Svc", (Svc,), {"name": name})
        r.register(name, cls)
    return r


def test_defaults(tmp_path: Path):
    s = build_settings(env={}, registry=make_registry(), default_data_dir=tmp_path)
    assert s.services == ["bigquery", "gcs"]
    assert s.persist is False
    assert s.data_dir == tmp_path
    assert s.admin_port == 4510
    assert s.port_overrides == {}


def test_services_subset(tmp_path: Path):
    s = build_settings(
        env={"SERVICES": "gcs"},
        registry=make_registry(),
        default_data_dir=tmp_path,
    )
    assert s.services == ["gcs"]


def test_persist_truthy(tmp_path: Path):
    for val in ("1", "true", "TRUE", "yes"):
        s = build_settings(
            env={"PERSIST": val},
            registry=make_registry(),
            default_data_dir=tmp_path,
        )
        assert s.persist is True, val


def test_persist_falsy(tmp_path: Path):
    for val in ("0", "false", "no", ""):
        s = build_settings(
            env={"PERSIST": val},
            registry=make_registry(),
            default_data_dir=tmp_path,
        )
        assert s.persist is False, val


def test_port_overrides(tmp_path: Path):
    s = build_settings(
        env={"GCS_EMULATOR_PORT": "5555", "BIGQUERY_EMULATOR_PORT": "9051"},
        registry=make_registry(),
        default_data_dir=tmp_path,
    )
    assert s.port_overrides == {"gcs": 5555, "bigquery": 9051}


def test_admin_port_override(tmp_path: Path):
    s = build_settings(
        env={"GCP_LOCAL_ADMIN_PORT": "4600"},
        registry=make_registry(),
        default_data_dir=tmp_path,
    )
    assert s.admin_port == 4600


def test_unknown_service_raises(tmp_path: Path):
    with pytest.raises(UnknownServiceError):
        build_settings(
            env={"SERVICES": "gcs,nope"},
            registry=make_registry(),
            default_data_dir=tmp_path,
        )
