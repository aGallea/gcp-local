import pytest

from gcp_local.core.registry import ServiceRegistry, UnknownServiceError
from gcp_local.core.service import HealthStatus, Port


class FakeA:
    name = "a"
    default_ports = [Port(1, "rest")]

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True)


class FakeB:
    name = "b"
    default_ports = [Port(2, "grpc")]

    async def start(self, ctx): ...
    async def stop(self): ...
    async def reset_state(self): ...
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True)


def test_register_and_get():
    r = ServiceRegistry()
    r.register("a", FakeA)
    assert r.get("a") is FakeA


def test_duplicate_registration_raises():
    r = ServiceRegistry()
    r.register("a", FakeA)
    with pytest.raises(ValueError, match="already registered"):
        r.register("a", FakeA)


def test_get_unknown_raises():
    r = ServiceRegistry()
    with pytest.raises(UnknownServiceError):
        r.get("nope")


def test_names_sorted():
    r = ServiceRegistry()
    r.register("b", FakeB)
    r.register("a", FakeA)
    assert r.names() == ["a", "b"]


def test_resolve_all():
    r = ServiceRegistry()
    r.register("a", FakeA)
    r.register("b", FakeB)
    assert r.resolve_selection("all") == ["a", "b"]


def test_resolve_subset():
    r = ServiceRegistry()
    r.register("a", FakeA)
    r.register("b", FakeB)
    assert r.resolve_selection("a") == ["a"]
    assert r.resolve_selection("a,b") == ["a", "b"]
    assert r.resolve_selection(" a , b ") == ["a", "b"]


def test_resolve_unknown_name_raises():
    r = ServiceRegistry()
    r.register("a", FakeA)
    with pytest.raises(UnknownServiceError, match="nope"):
        r.resolve_selection("a,nope")


def test_resolve_empty_is_empty():
    r = ServiceRegistry()
    r.register("a", FakeA)
    assert r.resolve_selection("") == []
