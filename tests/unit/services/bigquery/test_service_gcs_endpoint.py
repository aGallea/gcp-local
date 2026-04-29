"""GCS-URI endpoint resolution precedence inside BigQueryService."""

from pathlib import Path

import pytest

from gcp_local.core.context import Context
from gcp_local.services.bigquery.service import BigQueryService


def _ctx(*, gcs_port: int | None = None) -> Context:
    overrides: dict[str, int] = {}
    if gcs_port is not None:
        overrides["gcs"] = gcs_port
    return Context(persist=False, data_dir=Path("/tmp/gcp-local-test"), port_overrides=overrides)


def test_endpoint_defaults_to_loopback_with_default_gcs_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIGQUERY_GCS_URI_ENDPOINT", raising=False)
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)
    svc = BigQueryService()
    assert svc._resolve_gcs_endpoint(_ctx()) == "http://127.0.0.1:4443"


def test_endpoint_uses_port_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIGQUERY_GCS_URI_ENDPOINT", raising=False)
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)
    svc = BigQueryService()
    assert svc._resolve_gcs_endpoint(_ctx(gcs_port=12345)) == "http://127.0.0.1:12345"


def test_storage_emulator_host_takes_precedence_over_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIGQUERY_GCS_URI_ENDPOINT", raising=False)
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", "http://gcs.example:8080")
    svc = BigQueryService()
    assert svc._resolve_gcs_endpoint(_ctx(gcs_port=12345)) == "http://gcs.example:8080"


def test_storage_emulator_host_without_scheme_gets_http_prefixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIGQUERY_GCS_URI_ENDPOINT", raising=False)
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", "gcs.example:8080")
    svc = BigQueryService()
    assert svc._resolve_gcs_endpoint(_ctx()) == "http://gcs.example:8080"


def test_bigquery_specific_override_wins_over_storage_emulator_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIGQUERY_GCS_URI_ENDPOINT", "http://override.example")
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", "http://gcs.example:8080")
    svc = BigQueryService()
    assert svc._resolve_gcs_endpoint(_ctx(gcs_port=12345)) == "http://override.example"
