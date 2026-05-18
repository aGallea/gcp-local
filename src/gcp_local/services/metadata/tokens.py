"""Stub-token builders for the fake GCE metadata server.

These intentionally produce non-cryptographically-valid tokens. The emulator
ignores token values, and pointing the resulting token at real Google fails
cleanly with a 401 — there is no scenario in which a stub token authorizes
a real call.
"""

from typing import Final

_ACCESS_TOKEN_VALUE: Final = "ya29.gcp-local-stub-token"
_TOKEN_LIFETIME_SECONDS: Final = 3600


def build_access_token() -> dict[str, str | int]:
    """Return the JSON body for `/instance/service-accounts/{alias}/token`."""
    return {
        "access_token": _ACCESS_TOKEN_VALUE,
        "expires_in": _TOKEN_LIFETIME_SECONDS,
        "token_type": "Bearer",
    }
