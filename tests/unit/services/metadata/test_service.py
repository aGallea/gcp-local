"""Lifecycle / wiring tests for MetadataService."""

from gcp_local.core.registry import ServiceRegistry


def test_metadata_service_is_discovered_via_entry_points() -> None:
    registry = ServiceRegistry()
    registry.discover_from_entry_points()
    assert "metadata" in registry.names()


def test_metadata_service_is_included_in_default_all_selection() -> None:
    registry = ServiceRegistry()
    registry.discover_from_entry_points()
    assert "metadata" in registry.resolve_selection("all")
