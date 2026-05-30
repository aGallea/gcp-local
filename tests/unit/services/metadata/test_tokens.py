"""Tests for the stub token builders."""

import base64
import json

from gcp_local.services.metadata.tokens import (
    STUB_TOKEN_PREFIX,
    build_access_token,
    build_id_token,
    decode_stub_token_email,
)

_TEST_EMAIL = "svc@local-dev.iam.gserviceaccount.com"


def test_build_access_token_returns_documented_shape() -> None:
    token = build_access_token(_TEST_EMAIL)
    assert token["expires_in"] == 3600
    assert token["token_type"] == "Bearer"
    assert token["access_token"].startswith(STUB_TOKEN_PREFIX)


def test_build_access_token_encodes_email_in_token() -> None:
    token = build_access_token(_TEST_EMAIL)
    assert decode_stub_token_email(token["access_token"]) == _TEST_EMAIL


def test_decode_stub_token_email_returns_none_for_unrecognized() -> None:
    assert decode_stub_token_email("ya29.gcp-local-stub-token") is None
    assert decode_stub_token_email("Bearer something") is None
    assert decode_stub_token_email("") is None


def _decode_jwt_payload(jwt: str) -> dict[str, object]:
    """Decode the JWT payload without verifying the signature."""
    payload_b64 = jwt.split(".")[1]
    # base64url decode with padding compensation
    padding = "=" * (-len(payload_b64) % 4)
    payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
    decoded = json.loads(payload_bytes)
    assert isinstance(decoded, dict)
    return decoded


def test_build_id_token_returns_parseable_jwt_with_correct_claims() -> None:
    jwt = build_id_token(
        audience="https://example.test/api",
        email="me@example.iam.gserviceaccount.com",
        numeric_project_id="42",
    )

    parts = jwt.split(".")
    assert len(parts) == 3, "JWT must be header.payload.signature"

    payload = _decode_jwt_payload(jwt)
    assert payload["aud"] == "https://example.test/api"
    assert payload["email"] == "me@example.iam.gserviceaccount.com"
    assert payload["azp"] == "me@example.iam.gserviceaccount.com"
    assert payload["sub"] == "42"
    assert payload["iss"] == "https://accounts.google.com"
    assert payload["email_verified"] is True

    iat = payload["iat"]
    exp = payload["exp"]
    assert isinstance(iat, int)
    assert isinstance(exp, int)
    assert exp - iat == 3600


def test_build_id_token_header_advertises_RS256_and_stub_kid() -> None:
    jwt = build_id_token(
        audience="aud",
        email="e@x",
        numeric_project_id="0",
    )
    header_b64 = jwt.split(".")[0]
    padding = "=" * (-len(header_b64) % 4)
    header = json.loads(base64.urlsafe_b64decode(header_b64 + padding))
    assert header == {"alg": "RS256", "kid": "gcp-local-stub", "typ": "JWT"}
