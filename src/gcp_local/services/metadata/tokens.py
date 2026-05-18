"""Stub-token builders for the fake GCE metadata server.

These intentionally produce non-cryptographically-valid tokens. The emulator
ignores token values, and pointing the resulting token at real Google fails
cleanly with a 401 — there is no scenario in which a stub token authorizes
a real call.
"""

import base64
import json
import time
from collections.abc import Mapping
from typing import Final

_ACCESS_TOKEN_VALUE: Final = "ya29.gcp-local-stub-token"
_TOKEN_LIFETIME_SECONDS: Final = 3600

_JWT_HEADER: Final[dict[str, str]] = {"alg": "RS256", "kid": "gcp-local-stub", "typ": "JWT"}
_JWT_ISSUER: Final = "https://accounts.google.com"
_JWT_STUB_SIGNATURE: Final = b"gcp-local-stub-signature"


def build_access_token() -> dict[str, str | int]:
    """Return the JSON body for `/instance/service-accounts/{alias}/token`."""
    return {
        "access_token": _ACCESS_TOKEN_VALUE,
        "expires_in": _TOKEN_LIFETIME_SECONDS,
        "token_type": "Bearer",
    }


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(obj: Mapping[str, object]) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def build_id_token(*, audience: str, email: str, numeric_project_id: str) -> str:
    """Return a stub ID-token JWT bound to `audience`.

    The token is structurally a valid JWT (header.payload.signature, all
    base64url-encoded), but the signature is a fixed placeholder string —
    not a real RS256 signature. Anything that verifies the signature against
    Google's JWKS will (correctly) reject this token.
    """
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": _JWT_ISSUER,
        "aud": audience,
        "sub": numeric_project_id,
        "azp": email,
        "email": email,
        "email_verified": True,
        "iat": now,
        "exp": now + _TOKEN_LIFETIME_SECONDS,
    }
    return ".".join(
        [
            _b64url_json(_JWT_HEADER),
            _b64url_json(payload),
            _b64url(_JWT_STUB_SIGNATURE),
        ]
    )
