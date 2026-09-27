from pathlib import Path

from gcp_local.core.context import Context
from gcp_local.core.service import Port


def test_context_fields(tmp_path: Path):
    ctx = Context(
        persist=True,
        data_dir=tmp_path,
        port_overrides={"gcs": 5555},
    )
    assert ctx.persist is True
    assert ctx.data_dir == tmp_path
    assert ctx.port_overrides["gcs"] == 5555


def test_context_defaults(tmp_path: Path):
    ctx = Context(persist=False, data_dir=tmp_path)
    assert ctx.port_overrides == {}


def test_port_for_returns_the_default_when_not_overridden(tmp_path: Path):
    ctx = Context(persist=False, data_dir=tmp_path)
    assert ctx.port_for("gcs", Port(4443, "rest")) == 4443
    assert ctx.port_for("gcs", Port(4444, "grpc", name="grpc")) == 4444


def test_port_for_keys_the_primary_port_by_service_and_named_ports_by_suffix(tmp_path: Path):
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"gcs": 5555, "gcs_grpc": 5556})
    assert ctx.port_for("gcs", Port(4443, "rest")) == 5555
    assert ctx.port_for("gcs", Port(4444, "grpc", name="grpc")) == 5556


def test_overriding_the_primary_port_leaves_a_named_port_at_its_default(tmp_path: Path):
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"gcs": 5555})
    assert ctx.port_for("gcs", Port(4444, "grpc", name="grpc")) == 4444
