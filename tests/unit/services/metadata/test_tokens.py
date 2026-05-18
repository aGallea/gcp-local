"""Tests for the stub token builders."""

from gcp_local.services.metadata.tokens import (  # noqa: F401
    build_access_token,
    build_id_token,
)


def test_build_access_token_returns_documented_shape() -> None:
    token = build_access_token()
    assert token == {
        "access_token": "ya29.gcp-local-stub-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
