from pathlib import Path

from gcp_local.core.context import Context


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
