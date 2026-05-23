import socket
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
    assert ctx.sockets == {}


def test_context_sockets_field(tmp_path: Path):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    try:
        ctx = Context(persist=False, data_dir=tmp_path, sockets={"gcs": s})
        assert ctx.sockets["gcs"] is s
    finally:
        s.close()


def test_context_sockets_default_is_independent(tmp_path: Path):
    ctx1 = Context(persist=False, data_dir=tmp_path)
    ctx2 = Context(persist=False, data_dir=tmp_path)
    ctx1.sockets["x"] = None  # type: ignore[assignment]
    assert "x" not in ctx2.sockets
