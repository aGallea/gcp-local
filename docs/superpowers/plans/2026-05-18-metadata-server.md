# GCE Metadata Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a fake GCE metadata server as a default-on `gcp-local` service so unmodified ADC client code (`bigquery.Client()` with no `AnonymousCredentials`) can mint a stub token and talk to the emulator just like it talks to real GCP under Workload Identity.

**Architecture:** A new `MetadataService` registered in the existing `gcp_local.services` entry-point group. Single-file FastAPI app (`app.py`) serving `/computeMetadata/v1/...`. Pure-function token builders in `tokens.py` (stub access token + real-format JWT with stub signature). No storage, no state, no `Context.persist` branch. All configuration read from env vars at request time (port is read once at startup).

**Tech Stack:** Python 3.13, FastAPI, uvicorn (already in runtime deps). No new dependencies — the ID-token JWT is built with stdlib `json` + `base64`. Test dependencies: `httpx` (already runtime), `google-auth` and `google-cloud-bigquery` (already dev deps).

**Spec:** `docs/superpowers/specs/2026-05-18-metadata-server-design.md`

**Commit policy:** One commit per task, on branch `feat/metadata-server`. Use Conventional Commit subjects (`feat:`, `test:`, `docs:`).

---

## File map

| Path | Action | Responsibility |
|---|---|---|
| `src/gcp_local/services/metadata/__init__.py` | Create | Re-export `MetadataService` |
| `src/gcp_local/services/metadata/service.py` | Create | Service-protocol lifecycle |
| `src/gcp_local/services/metadata/app.py` | Create | FastAPI app factory + routes + middleware |
| `src/gcp_local/services/metadata/tokens.py` | Create | `build_access_token()`, `build_id_token()` |
| `tests/unit/services/metadata/__init__.py` | Create | Empty test package marker |
| `tests/unit/services/metadata/test_tokens.py` | Create | Unit tests for token builders |
| `tests/unit/services/metadata/test_app.py` | Create | Route-level tests via `httpx.AsyncClient` |
| `tests/unit/services/metadata/test_service.py` | Create | Lifecycle unit tests |
| `tests/integration/conftest.py` | Modify | Register `MetadataService` + allocate metadata port |
| `tests/integration/test_metadata_integration.py` | Create | `google-auth` and `google-cloud-bigquery` end-to-end tests |
| `pyproject.toml` | Modify | Add `metadata` entry point |
| `docs/services/metadata.md` | Create | User-facing usage doc |
| `docs/architecture/metadata.md` | Create | Internals doc |
| `README.md` | Modify | Add `metadata` row to services-at-a-glance table |
| `docs/deployment.md` | Modify | Add `Metadata server` row + paragraph |

---

## Task 1: Package skeleton + entry-point registration

**Files:**
- Create: `src/gcp_local/services/metadata/__init__.py`
- Create: `src/gcp_local/services/metadata/service.py`
- Create: `tests/unit/services/metadata/__init__.py`
- Modify: `pyproject.toml` (entry points block)

- [ ] **Step 1: Write the failing discovery test**

Create `tests/unit/services/metadata/__init__.py` as an empty file, then create `tests/unit/services/metadata/test_service.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/services/metadata/test_service.py -v`
Expected: FAIL with `assert "metadata" in [...]` — service not registered yet.

- [ ] **Step 3: Create the MetadataService stub**

Create `src/gcp_local/services/metadata/service.py`:

```python
"""Fake GCE metadata server.

Exposes /computeMetadata/v1/... endpoints that satisfy google-auth's
ComputeEngineCredentials path, so unmodified ADC client code can mint a
stub token and route subsequent calls to the rest of gcp-local.
"""

import asyncio
import logging
from typing import ClassVar

import uvicorn

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8091


class MetadataService:
    """Emulates the GCE metadata server."""

    name = "metadata"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def reset_state(self) -> None:
        pass

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
```

Create `src/gcp_local/services/metadata/__init__.py`:

```python
from gcp_local.services.metadata.service import MetadataService

__all__ = ["MetadataService"]
```

- [ ] **Step 4: Register the entry point**

Edit `pyproject.toml`, locating this block:

```toml
[project.entry-points."gcp_local.services"]
gcs = "gcp_local.services.gcs:GcsService"
secret_manager = "gcp_local.services.secret_manager:SecretManagerService"
bigquery = "gcp_local.services.bigquery:BigQueryService"
pubsub = "gcp_local.services.pubsub:PubSubService"
firestore = "gcp_local.services.firestore:FirestoreService"
```

Append a single line so it reads:

```toml
[project.entry-points."gcp_local.services"]
gcs = "gcp_local.services.gcs:GcsService"
secret_manager = "gcp_local.services.secret_manager:SecretManagerService"
bigquery = "gcp_local.services.bigquery:BigQueryService"
pubsub = "gcp_local.services.pubsub:PubSubService"
firestore = "gcp_local.services.firestore:FirestoreService"
metadata = "gcp_local.services.metadata:MetadataService"
```

Reinstall the package so the entry point takes effect:

```bash
pip install -e .
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_service.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gcp_local/services/metadata/__init__.py \
        src/gcp_local/services/metadata/service.py \
        tests/unit/services/metadata/__init__.py \
        tests/unit/services/metadata/test_service.py \
        pyproject.toml
git commit -m "feat(metadata): scaffold MetadataService and entry point"
```

---

## Task 2: `build_access_token`

**Files:**
- Create: `src/gcp_local/services/metadata/tokens.py`
- Create: `tests/unit/services/metadata/test_tokens.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/services/metadata/test_tokens.py`:

```python
"""Tests for the stub token builders."""

import base64
import json

from gcp_local.services.metadata.tokens import build_access_token, build_id_token


def test_build_access_token_returns_documented_shape() -> None:
    token = build_access_token()
    assert token == {
        "access_token": "ya29.gcp-local-stub-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/services/metadata/test_tokens.py::test_build_access_token_returns_documented_shape -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `build_access_token`**

Create `src/gcp_local/services/metadata/tokens.py`:

```python
"""Stub-token builders for the fake GCE metadata server.

These intentionally produce non-cryptographically-valid tokens. The emulator
ignores token values, and pointing the resulting token at real Google fails
cleanly with a 401 — there is no scenario in which a stub token authorizes
a real call.
"""

import base64
import json
import time
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/services/metadata/test_tokens.py::test_build_access_token_returns_documented_shape -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/tokens.py tests/unit/services/metadata/test_tokens.py
git commit -m "feat(metadata): build_access_token returns stub Bearer token"
```

---

## Task 3: `build_id_token`

**Files:**
- Modify: `src/gcp_local/services/metadata/tokens.py`
- Modify: `tests/unit/services/metadata/test_tokens.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/services/metadata/test_tokens.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/services/metadata/test_tokens.py -v`
Expected: the two new tests FAIL with `ImportError` / `AttributeError`.

- [ ] **Step 3: Implement `build_id_token`**

Append to `src/gcp_local/services/metadata/tokens.py`:

```python
_JWT_HEADER: Final = {"alg": "RS256", "kid": "gcp-local-stub", "typ": "JWT"}
_JWT_ISSUER: Final = "https://accounts.google.com"
_JWT_STUB_SIGNATURE: Final = b"gcp-local-stub-signature"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(obj: dict[str, object]) -> str:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_tokens.py -v`
Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/tokens.py tests/unit/services/metadata/test_tokens.py
git commit -m "feat(metadata): build_id_token returns audience-bound JWT"
```

---

## Task 4: App factory + Metadata-Flavor middleware

**Files:**
- Create: `src/gcp_local/services/metadata/app.py`
- Create: `tests/unit/services/metadata/test_app.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/services/metadata/test_app.py`:

```python
"""Route-level tests for the metadata server."""

import httpx
import pytest

from gcp_local.services.metadata.app import build_app


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app()), base_url="http://meta")


async def test_request_without_metadata_flavor_header_is_rejected_with_403(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get("/")
    assert resp.status_code == 403
    assert "Metadata-Flavor" in resp.text


async def test_response_always_includes_metadata_flavor_google_header(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get("/", headers={"Metadata-Flavor": "Google"})
    assert resp.status_code == 200
    assert resp.headers["Metadata-Flavor"] == "Google"


async def test_403_response_also_includes_metadata_flavor_header(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get("/")
    assert resp.headers["Metadata-Flavor"] == "Google"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/services/metadata/test_app.py -v`
Expected: FAIL with `ImportError` for `build_app`.

- [ ] **Step 3: Implement the app factory and middleware**

Create `src/gcp_local/services/metadata/app.py`:

```python
"""FastAPI app for the fake GCE metadata server."""

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

_METADATA_FLAVOR_HEADER = "Metadata-Flavor"
_METADATA_FLAVOR_VALUE = "Google"


class MetadataFlavorMiddleware(BaseHTTPMiddleware):
    """Enforce and echo the `Metadata-Flavor: Google` header.

    Real GCE returns 403 when a request omits this header (so a client can
    detect a fake server that doesn't enforce it). google-auth always sends
    it, and also checks that responses carry the same header in return.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.headers.get(_METADATA_FLAVOR_HEADER) != _METADATA_FLAVOR_VALUE:
            return PlainTextResponse(
                "Missing required Metadata-Flavor header.",
                status_code=403,
                headers={_METADATA_FLAVOR_HEADER: _METADATA_FLAVOR_VALUE},
            )
        response: Response = await call_next(request)
        response.headers[_METADATA_FLAVOR_HEADER] = _METADATA_FLAVOR_VALUE
        return response


def build_app() -> FastAPI:
    app = FastAPI(title="gcp-local metadata", version="0.0.1")
    app.add_middleware(MetadataFlavorMiddleware)

    @app.get("/", response_class=PlainTextResponse)
    async def _probe() -> str:
        return "computeMetadata/\n"

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_app.py -v`
Expected: three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/app.py tests/unit/services/metadata/test_app.py
git commit -m "feat(metadata): app factory enforces Metadata-Flavor header"
```

---

## Task 5: Project endpoints

**Files:**
- Modify: `src/gcp_local/services/metadata/app.py`
- Modify: `tests/unit/services/metadata/test_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/metadata/test_app.py`:

```python
async def test_project_id_default_is_local_dev(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "local-dev"


async def test_project_id_honors_GOOGLE_CLOUD_PROJECT_env(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text == "my-proj"


async def test_numeric_project_id_default_is_zero(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/numeric-project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text == "0"


async def test_numeric_project_id_honors_env(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METADATA_NUMERIC_PROJECT_ID", "1234567890")
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/project/numeric-project-id",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text == "1234567890"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/services/metadata/test_app.py -k project -v`
Expected: four tests FAIL with `404 Not Found`.

- [ ] **Step 3: Add project endpoints to the app**

Edit `src/gcp_local/services/metadata/app.py`. Add an `import os` to the top, then add a `_config` helper and two routes inside `build_app()`. The full updated file:

```python
"""FastAPI app for the fake GCE metadata server."""

import os

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

_METADATA_FLAVOR_HEADER = "Metadata-Flavor"
_METADATA_FLAVOR_VALUE = "Google"

_DEFAULT_PROJECT_ID = "local-dev"
_DEFAULT_NUMERIC_PROJECT_ID = "0"


def _project_id() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT") or _DEFAULT_PROJECT_ID


def _numeric_project_id() -> str:
    return os.environ.get("METADATA_NUMERIC_PROJECT_ID") or _DEFAULT_NUMERIC_PROJECT_ID


class MetadataFlavorMiddleware(BaseHTTPMiddleware):
    """Enforce and echo the `Metadata-Flavor: Google` header."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.headers.get(_METADATA_FLAVOR_HEADER) != _METADATA_FLAVOR_VALUE:
            return PlainTextResponse(
                "Missing required Metadata-Flavor header.",
                status_code=403,
                headers={_METADATA_FLAVOR_HEADER: _METADATA_FLAVOR_VALUE},
            )
        response: Response = await call_next(request)
        response.headers[_METADATA_FLAVOR_HEADER] = _METADATA_FLAVOR_VALUE
        return response


def build_app() -> FastAPI:
    app = FastAPI(title="gcp-local metadata", version="0.0.1")
    app.add_middleware(MetadataFlavorMiddleware)

    @app.get("/", response_class=PlainTextResponse)
    async def _probe() -> str:
        return "computeMetadata/\n"

    @app.get("/computeMetadata/v1/project/project-id", response_class=PlainTextResponse)
    async def _project_id_route() -> str:
        return _project_id()

    @app.get("/computeMetadata/v1/project/numeric-project-id", response_class=PlainTextResponse)
    async def _numeric_project_id_route() -> str:
        return _numeric_project_id()

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_app.py -v`
Expected: all tests in the file PASS (previous three + four new).

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/app.py tests/unit/services/metadata/test_app.py
git commit -m "feat(metadata): /project/project-id and /project/numeric-project-id"
```

---

## Task 6: Service-account listing, recursive view, email, scopes

**Files:**
- Modify: `src/gcp_local/services/metadata/app.py`
- Modify: `tests/unit/services/metadata/test_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/metadata/test_app.py`:

```python
DEFAULT_EMAIL = "default@local-dev.iam.gserviceaccount.com"


async def test_service_accounts_listing_includes_default_and_configured_email(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body_lines = resp.text.strip().splitlines()
    assert "default/" in body_lines
    assert f"{DEFAULT_EMAIL}/" in body_lines


async def test_email_endpoint_returns_configured_email(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.text == DEFAULT_EMAIL


async def test_email_endpoint_works_for_email_alias(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METADATA_SERVICE_ACCOUNT_EMAIL", "bot@x.iam.gserviceaccount.com")
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/bot@x.iam.gserviceaccount.com/email",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.text == "bot@x.iam.gserviceaccount.com"


async def test_email_endpoint_rejects_unknown_alias_with_404(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/nobody/email",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 404


async def test_scopes_endpoint_default_returns_cloud_platform(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/scopes",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.text.strip() == "https://www.googleapis.com/auth/cloud-platform"


async def test_scopes_endpoint_honors_env(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "METADATA_SCOPES",
        "https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/cloud-platform",
    )
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/scopes",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.text.splitlines() == [
        "https://www.googleapis.com/auth/devstorage.read_only",
        "https://www.googleapis.com/auth/cloud-platform",
    ]


async def test_recursive_view_returns_email_aliases_and_scopes(
    client: httpx.AsyncClient,
) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/?recursive=true",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == DEFAULT_EMAIL
    assert "default" in body["aliases"]
    assert body["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/services/metadata/test_app.py -v`
Expected: the seven new tests FAIL with 404.

- [ ] **Step 3: Add a config helper and the routes**

Edit `src/gcp_local/services/metadata/app.py`. Add the helpers above `build_app` and the routes inside it:

```python
_DEFAULT_EMAIL = "default@local-dev.iam.gserviceaccount.com"
_DEFAULT_SCOPES = "https://www.googleapis.com/auth/cloud-platform"


def _email() -> str:
    return os.environ.get("METADATA_SERVICE_ACCOUNT_EMAIL") or _DEFAULT_EMAIL


def _scopes() -> list[str]:
    raw = os.environ.get("METADATA_SCOPES") or _DEFAULT_SCOPES
    return [s.strip() for s in raw.split(",") if s.strip()]


def _resolve_alias(alias: str) -> str | None:
    """Return the canonical alias ('default') or None for an unknown alias."""
    if alias == "default" or alias == _email():
        return "default"
    return None
```

And inside `build_app()`, add these routes (just before `return app`):

```python
    @app.get("/computeMetadata/v1/instance/service-accounts/", response_class=PlainTextResponse)
    async def _sa_listing() -> str:
        return f"default/\n{_email()}/\n"

    @app.get("/computeMetadata/v1/instance/service-accounts/{alias}/")
    async def _sa_recursive(alias: str, recursive: str | None = None) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        return _json_response({
            "aliases": ["default"],
            "email": _email(),
            "scopes": _scopes(),
        })

    @app.get(
        "/computeMetadata/v1/instance/service-accounts/{alias}/email",
        response_class=PlainTextResponse,
    )
    async def _sa_email(alias: str) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        return PlainTextResponse(_email())

    @app.get(
        "/computeMetadata/v1/instance/service-accounts/{alias}/scopes",
        response_class=PlainTextResponse,
    )
    async def _sa_scopes(alias: str) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        return PlainTextResponse("\n".join(_scopes()) + "\n")
```

Add this helper at module level (near `_email` etc.):

```python
def _json_response(body: dict[str, object]) -> Response:
    """A JSONResponse-equivalent that doesn't strip middleware-added headers."""
    import json as _json

    return Response(
        content=_json.dumps(body),
        media_type="application/json",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_app.py -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/app.py tests/unit/services/metadata/test_app.py
git commit -m "feat(metadata): service-account listing, recursive, email, scopes"
```

---

## Task 7: Access token endpoint

**Files:**
- Modify: `src/gcp_local/services/metadata/app.py`
- Modify: `tests/unit/services/metadata/test_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/services/metadata/test_app.py`:

```python
async def test_token_endpoint_returns_stub_access_token(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["access_token"] == "ya29.gcp-local-stub-token"
    assert body["expires_in"] == 3600
    assert body["token_type"] == "Bearer"


async def test_token_endpoint_accepts_and_ignores_scopes_query(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/token?scopes=a,b",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "ya29.gcp-local-stub-token"


async def test_token_endpoint_rejects_unknown_alias_with_404(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/nobody/token",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/services/metadata/test_app.py -k token -v`
Expected: three new tests FAIL with 404 on the matching path.

- [ ] **Step 3: Add the token endpoint**

Add `from gcp_local.services.metadata.tokens import build_access_token` at the top of `app.py`. Then add this route inside `build_app()`:

```python
    @app.get("/computeMetadata/v1/instance/service-accounts/{alias}/token")
    async def _sa_token(alias: str, scopes: str | None = None) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        return _json_response(build_access_token())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_app.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/app.py tests/unit/services/metadata/test_app.py
git commit -m "feat(metadata): /token returns stub access token"
```

---

## Task 8: Identity token endpoint

**Files:**
- Modify: `src/gcp_local/services/metadata/app.py`
- Modify: `tests/unit/services/metadata/test_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/metadata/test_app.py`:

```python
async def test_identity_endpoint_returns_jwt_with_audience(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/identity",
            params={"audience": "https://service.example/api"},
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 200
    jwt = resp.text
    parts = jwt.split(".")
    assert len(parts) == 3
    import base64 as _b64
    import json as _json

    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    payload = _json.loads(_b64.urlsafe_b64decode(payload_b64 + padding))
    assert payload["aud"] == "https://service.example/api"


async def test_identity_endpoint_without_audience_returns_400(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/identity",
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 400
    assert "audience" in resp.text


async def test_identity_endpoint_with_empty_audience_returns_400(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/default/identity",
            params={"audience": ""},
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 400


async def test_identity_endpoint_rejects_unknown_alias_with_404(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.get(
            "/computeMetadata/v1/instance/service-accounts/nobody/identity",
            params={"audience": "a"},
            headers={"Metadata-Flavor": "Google"},
        )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/services/metadata/test_app.py -k identity -v`
Expected: four tests FAIL.

- [ ] **Step 3: Add the identity endpoint**

Add `from gcp_local.services.metadata.tokens import build_access_token, build_id_token` (extend the existing import) at the top of `app.py`. Then add this route inside `build_app()`:

```python
    @app.get(
        "/computeMetadata/v1/instance/service-accounts/{alias}/identity",
        response_class=PlainTextResponse,
    )
    async def _sa_identity(alias: str, audience: str | None = None) -> Response:
        if _resolve_alias(alias) is None:
            return PlainTextResponse("alias not found", status_code=404)
        if not audience:
            return PlainTextResponse(
                "non-empty audience parameter required",
                status_code=400,
            )
        return PlainTextResponse(
            build_id_token(
                audience=audience,
                email=_email(),
                numeric_project_id=_numeric_project_id(),
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_app.py -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/app.py tests/unit/services/metadata/test_app.py
git commit -m "feat(metadata): /identity returns audience-bound JWT"
```

---

## Task 9: MetadataService lifecycle (uvicorn server)

**Files:**
- Modify: `src/gcp_local/services/metadata/service.py`
- Modify: `tests/unit/services/metadata/test_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/metadata/test_service.py`:

```python
import asyncio
import socket
from pathlib import Path

import httpx
import pytest

from gcp_local.core.context import Context
from gcp_local.services.metadata import MetadataService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.02)
    raise TimeoutError(f"port {port} did not open within {timeout}s")


@pytest.mark.asyncio
async def test_service_start_binds_port_and_serves_requests(tmp_path: Path) -> None:
    port = _free_port()
    svc = MetadataService()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"metadata": port})
    await svc.start(ctx)
    try:
        await _wait_for_port(port)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            resp = await client.get(
                "/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
            assert resp.status_code == 200
            assert resp.text == "local-dev"
    finally:
        await svc.stop()


@pytest.mark.asyncio
async def test_service_health_reflects_lifecycle(tmp_path: Path) -> None:
    svc = MetadataService()
    assert svc.health().ok is False
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"metadata": _free_port()})
    await svc.start(ctx)
    try:
        assert svc.health().ok is True
    finally:
        await svc.stop()
    assert svc.health().ok is False


@pytest.mark.asyncio
async def test_service_reset_state_is_a_noop(tmp_path: Path) -> None:
    svc = MetadataService()
    ctx = Context(persist=False, data_dir=tmp_path, port_overrides={"metadata": _free_port()})
    await svc.start(ctx)
    try:
        await svc.reset_state()  # must not raise
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{ctx.port_overrides['metadata']}"
        ) as client:
            resp = await client.get(
                "/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
            assert resp.status_code == 200
    finally:
        await svc.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/services/metadata/test_service.py -v`
Expected: the three new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `start` and `stop`**

Replace the body of `MetadataService.start` and `MetadataService.stop` in `src/gcp_local/services/metadata/service.py`:

```python
import asyncio
import logging
from typing import ClassVar

import uvicorn

from gcp_local.core.context import Context
from gcp_local.core.service import HealthStatus, Port
from gcp_local.services.metadata.app import build_app

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8091


class MetadataService:
    """Emulates the GCE metadata server."""

    name = "metadata"
    default_ports: ClassVar[list[Port]] = [Port(_DEFAULT_PORT, "rest")]

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self, ctx: Context) -> None:
        port = ctx.port_overrides.get(self.name, _DEFAULT_PORT)
        app = build_app()
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        self._server_task = asyncio.create_task(self._server.serve(), name=f"{self.name}-server")
        self._started = True
        log.info(
            "metadata service listening on :%d "
            "(clients: set GCE_METADATA_HOST=<host>:%d)",
            port,
            port,
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        self._started = False

    async def reset_state(self) -> None:
        pass

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self._started, message="running" if self._started else "stopped")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/metadata/test_service.py -v`
Expected: all five tests PASS (two discovery + three lifecycle).

- [ ] **Step 5: Commit**

```bash
git add src/gcp_local/services/metadata/service.py tests/unit/services/metadata/test_service.py
git commit -m "feat(metadata): wire uvicorn lifecycle in MetadataService"
```

---

## Task 10: Register MetadataService in integration conftest

**Files:**
- Modify: `tests/integration/conftest.py`

- [ ] **Step 1: Read the current fixture**

Open `tests/integration/conftest.py` and identify the `emulator` fixture (the block starting `async def emulator(...)`).

- [ ] **Step 2: Update the fixture**

Make these edits:

1. Add `from gcp_local.services.metadata import MetadataService` to the import block where other services are imported.

2. Inside `emulator`, after `registry.register("firestore", FirestoreService)`, add:

```python
    registry.register("metadata", MetadataService)
```

3. Add `metadata_port = _free_port()` to the port-allocation block.

4. Append `"metadata"` to the `services=[...]` list in the `Settings(...)` call.

5. Append `"metadata": metadata_port` to the `port_overrides={...}` dict.

6. Append `await _wait_for_port(metadata_port)` after the other `_wait_for_port` calls.

7. Append `"metadata_port": metadata_port,` to the `yield {...}` dict.

8. In the `emulator_endpoints` fixture, append `"metadata": f"127.0.0.1:{emulator['metadata_port']}",` to the returned dict.

- [ ] **Step 3: Verify existing integration tests still pass**

Run: `pytest tests/integration/test_core_end_to_end.py -v`
Expected: PASS (existing core e2e still works with the metadata service running).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "test(metadata): register MetadataService in integration emulator fixture"
```

---

## Task 11: Integration test — google-auth ComputeEngineCredentials

**Files:**
- Create: `tests/integration/test_metadata_integration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_metadata_integration.py`:

```python
"""End-to-end tests for the metadata server using real google-auth."""

import pytest
from google.auth import compute_engine
from google.auth.transport import requests as ga_requests


@pytest.fixture(autouse=True)
def _point_google_auth_at_emulator(
    emulator: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make google-auth treat the local metadata server as the GCE metadata server."""
    metadata_host = f"127.0.0.1:{emulator['metadata_port']}"
    monkeypatch.setenv("GCE_METADATA_HOST", metadata_host)
    monkeypatch.setenv("GCE_METADATA_IP", metadata_host)
    # Prevent ADC from falling back to user creds during the test.
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)


def test_compute_engine_credentials_refresh_against_emulator(
    emulator: dict[str, int],
) -> None:
    creds = compute_engine.Credentials()
    creds.refresh(ga_requests.Request())
    assert creds.token == "ya29.gcp-local-stub-token"
    assert creds.service_account_email.endswith("local-dev.iam.gserviceaccount.com")
```

- [ ] **Step 2: Run test to verify it passes (it should — service already works)**

Run: `pytest tests/integration/test_metadata_integration.py::test_compute_engine_credentials_refresh_against_emulator -v`
Expected: PASS.

If it FAILS, debug the metadata server first — this test exercises the same code paths the unit tests cover, just via the real client library.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_metadata_integration.py
git commit -m "test(metadata): google-auth ComputeEngineCredentials end-to-end"
```

---

## Task 12: Integration test — `google.auth.default()` and identity tokens

**Files:**
- Modify: `tests/integration/test_metadata_integration.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_metadata_integration.py`:

```python
import base64
import json

import google.auth
from google.auth import compute_engine
from google.oauth2 import id_token as id_token_module  # noqa: F401  # imported for side effects


def test_google_auth_default_picks_metadata_server() -> None:
    creds, project = google.auth.default()
    assert isinstance(creds, compute_engine.Credentials)
    assert project == "local-dev"


def test_id_token_audience_round_trip(emulator: dict[str, int]) -> None:
    creds = compute_engine.IDTokenCredentials(
        ga_requests.Request(),
        target_audience="https://service.example/api",
    )
    creds.refresh(ga_requests.Request())
    parts = creds.token.split(".")
    assert len(parts) == 3
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    assert payload["aud"] == "https://service.example/api"
    assert payload["email"].endswith("local-dev.iam.gserviceaccount.com")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_metadata_integration.py -v`
Expected: all three tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_metadata_integration.py
git commit -m "test(metadata): google.auth.default and id-token integration tests"
```

---

## Task 13: Integration test — BigQuery with plain ADC (smoke)

**Files:**
- Modify: `tests/integration/test_metadata_integration.py`

This test proves that production-shaped client code — `bigquery.Client(project=...)` with no `AnonymousCredentials`, no `client_options` — works against gcp-local. The metadata server's role is to satisfy the ADC chain so the client doesn't raise `DefaultCredentialsError` before ever sending a request. Note that `google-cloud-bigquery` short-circuits to anonymous credentials internally when `BIGQUERY_EMULATOR_HOST` is set, so this test does *not* prove the stub bearer token reaches the BigQuery service — that's what Task 12's `google.auth.default()` test covers. What this test does prove is that the **same call site that runs in production** doesn't break when run against gcp-local.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_metadata_integration.py`:

```python
def test_bigquery_client_works_with_plain_adc(emulator: dict[str, int]) -> None:
    """Production-shaped client code (no AnonymousCredentials, no client_options)
    must complete a query against gcp-local. The metadata server keeps ADC
    happy; BIGQUERY_EMULATOR_HOST routes traffic to the BigQuery emulator.
    """
    import os

    from google.cloud import bigquery

    os.environ["BIGQUERY_EMULATOR_HOST"] = f"127.0.0.1:{emulator['bigquery_port']}"
    try:
        client = bigquery.Client(project="local-dev")
        rows = list(client.query("SELECT 1 AS x").result())
        assert [r["x"] for r in rows] == [1]
    finally:
        os.environ.pop("BIGQUERY_EMULATOR_HOST", None)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/integration/test_metadata_integration.py::test_bigquery_client_works_with_plain_adc -v`
Expected: PASS.

If it FAILS with `DefaultCredentialsError`, the metadata server is not being reached — verify the autouse fixture is setting `GCE_METADATA_HOST` correctly. If it FAILS with a BigQuery-specific error, compare against `tests/integration/test_bigquery_integration.py` for the env-var pattern (but do **not** add `AnonymousCredentials` or `client_options` — that defeats the test).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_metadata_integration.py
git commit -m "test(metadata): production-shaped bigquery.Client works against gcp-local"
```

---

## Task 14: User-facing doc — `docs/services/metadata.md`

**Files:**
- Create: `docs/services/metadata.md`

- [ ] **Step 1: Write the doc**

Create `docs/services/metadata.md`:

```markdown
# Metadata server

The metadata server emulates the GCE/GKE metadata service that `google-auth` reaches at `metadata.google.internal` on production GKE. It exists so that unmodified ADC client code — the kind you ship to production — can run against `gcp-local` without forking the call site to inject `AnonymousCredentials`.

> Without the metadata server, `bigquery.Client()` in a local pod fails with `DefaultCredentialsError`. With it, the same line of code mints a stub token, sends it to the BigQuery emulator (which ignores it), and works.

## Status

Alpha. Stable enough for local development and CI; not a security boundary.

## Default port

`8091`. Override with `METADATA_EMULATOR_PORT`.

## What's emulated

- `GET /` — probe path used by `google-auth` to detect a metadata server. Returns `Metadata-Flavor: Google`.
- `GET /computeMetadata/v1/project/project-id` — returns `$GOOGLE_CLOUD_PROJECT` (default `local-dev`).
- `GET /computeMetadata/v1/project/numeric-project-id` — returns `$METADATA_NUMERIC_PROJECT_ID` (default `0`).
- `GET /computeMetadata/v1/instance/service-accounts/` — lists `default` and the configured email.
- `GET /computeMetadata/v1/instance/service-accounts/{default|<email>}/email` — returns `$METADATA_SERVICE_ACCOUNT_EMAIL` (default `default@local-dev.iam.gserviceaccount.com`).
- `GET /computeMetadata/v1/instance/service-accounts/{alias}/scopes` — returns `$METADATA_SCOPES` (default `https://www.googleapis.com/auth/cloud-platform`).
- `GET /computeMetadata/v1/instance/service-accounts/{alias}/token` — returns a stub access token (`ya29.gcp-local-stub-token`, `expires_in: 3600`).
- `GET /computeMetadata/v1/instance/service-accounts/{alias}/identity?audience=...` — returns a real-format JWT bound to the requested audience. Signature is a fixed placeholder; payload carries `aud`, `email`, `azp`, `sub`, `iss`, `iat`, `exp`.
- `GET /computeMetadata/v1/instance/service-accounts/{alias}/?recursive=true` — recursive JSON view.

Every request must include header `Metadata-Flavor: Google` (otherwise 403). Every response carries the same header back. `/identity` requires a non-empty `audience` query param (otherwise 400).

## What's not emulated

- **Token signatures.** Access tokens are fixed strings. ID-token JWTs have a placeholder signature that won't verify against Google's JWKS. The emulator services ignore tokens; real GCP services correctly reject them.
- **Multi-SA aliases.** Only `default` and the configured email-as-alias are served. Real GCE supports arbitrary attached service accounts.
- **`/instance/zone`, `/instance/name`, `/instance/id`, `/instance/attributes/*`, `/instance/network-interfaces/*`.** These are used by infrastructure tooling, not by `google-cloud-*` client libraries.
- **TLS.** Plain HTTP, like every other emulator endpoint.
- **`metadata.google.internal` DNS.** The server binds on a regular high port; pointing `metadata.google.internal` at it is your DNS / `hostAliases` / sidecar problem (see "Connecting" below).

## Connecting

`google-auth` reaches the metadata server through one of:

1. **`GCE_METADATA_HOST` env var** (recommended for local dev) — `host:port` string. No DNS rewrite needed.
2. **`metadata.google.internal` DNS** — only works if you've rewritten the hostname (via CoreDNS, `hostAliases`, a sidecar binding `127.0.0.1`, etc.) to point at this server **on port 80**, which usually means running a sidecar.

The `GCE_METADATA_HOST` approach is what you want unless you're trying to run unmodified third-party binaries that hardcode the magic hostname.

### From a Kubernetes pod (recommended pattern)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
    - name: app
      image: my-app:dev
      env:
        - name: GOOGLE_CLOUD_PROJECT
          value: local-dev
        - name: GCE_METADATA_HOST
          value: gcp-local.default.svc.cluster.local:8091
        - name: GCE_METADATA_IP
          value: gcp-local.default.svc.cluster.local:8091
        - name: BIGQUERY_EMULATOR_HOST
          value: gcp-local.default.svc.cluster.local:9050
        - name: STORAGE_EMULATOR_HOST
          value: http://gcp-local.default.svc.cluster.local:4443
        - name: PUBSUB_EMULATOR_HOST
          value: gcp-local.default.svc.cluster.local:8085
        - name: FIRESTORE_EMULATOR_HOST
          value: gcp-local.default.svc.cluster.local:8080
```

App code stays identical to production:

```python
from google.cloud import bigquery

bq = bigquery.Client()        # picks up GOOGLE_CLOUD_PROJECT
list(bq.query("SELECT 1").result())
```

No `AnonymousCredentials`, no `client_options`. ADC walks its chain, finds a reachable metadata server via `GCE_METADATA_HOST`, mints a token, and the BigQuery client routes its traffic through `BIGQUERY_EMULATOR_HOST` to the BigQuery emulator.

### From `docker-compose`

```yaml
services:
  gcp-local:
    image: gcp-local:dev
    ports: ["4510:4510", "4443:4443", "8086:8086", "8091:8091", "9050:9050"]
  app:
    image: my-app:dev
    environment:
      GOOGLE_CLOUD_PROJECT: local-dev
      GCE_METADATA_HOST: gcp-local:8091
      GCE_METADATA_IP:   gcp-local:8091
      BIGQUERY_EMULATOR_HOST: gcp-local:9050
      STORAGE_EMULATOR_HOST:  http://gcp-local:4443
    depends_on: [gcp-local]
```

### From a host shell

```bash
export GCE_METADATA_HOST=localhost:8091
export GCE_METADATA_IP=localhost:8091
export BIGQUERY_EMULATOR_HOST=localhost:9050
python -c "from google.cloud import bigquery; print(list(bigquery.Client(project='local-dev').query('SELECT 1').result()))"
```

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `METADATA_EMULATOR_PORT` | `8091` | Port to bind. |
| `METADATA_SERVICE_ACCOUNT_EMAIL` | `default@local-dev.iam.gserviceaccount.com` | Returned by `/email`; carried in the ID-token `email`/`azp` claims. |
| `GOOGLE_CLOUD_PROJECT` | `local-dev` | Returned by `/project/project-id`. Reused from the standard Google env var. |
| `METADATA_NUMERIC_PROJECT_ID` | `0` | Returned by `/project/numeric-project-id` and the JWT `sub` claim. |
| `METADATA_SCOPES` | `https://www.googleapis.com/auth/cloud-platform` | Comma-separated; returned newline-joined from `/scopes`. |

Only `METADATA_EMULATOR_PORT` is read at startup; the rest are read at request time, so you can change a value and see the next response reflect it without restarting `gcp-local`.

## Limits & quirks

- The metadata server runs on whatever process started it. It is **not** automatically reachable on `169.254.169.254` or `metadata.google.internal` — that's a DNS / network problem for the consumer, not something `gcp-local` solves.
- Tokens are stub strings. If a client accidentally calls real Google with one, the call fails cleanly with `401`. There is no scenario in which a stub token authorizes a real call.
- The service is part of the default `SERVICES=all` set. To run without it: `SERVICES=gcs,bigquery,pubsub,firestore,secret_manager`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/services/metadata.md
git commit -m "docs(metadata): add user-facing usage guide"
```

---

## Task 15: Architecture doc — `docs/architecture/metadata.md`

**Files:**
- Create: `docs/architecture/metadata.md`

- [ ] **Step 1: Write the doc**

Create `docs/architecture/metadata.md`:

```markdown
# Metadata server — architecture

Internals for the fake GCE metadata server. For user-facing usage, see [`docs/services/metadata.md`](../services/metadata.md).

## At a glance

- Single FastAPI app (REST, HTTP). One file: `src/gcp_local/services/metadata/app.py`.
- Lifecycle handled by `MetadataService` (`src/gcp_local/services/metadata/service.py`) — same uvicorn-server pattern as the GCS service.
- No storage. No state. No `Context.persist` branch. `reset_state` is a no-op.
- No coupling to other services: does not publish to `StateHub`, does not call into any sibling service.

## Wire & port

- Protocol: HTTP (plain, no TLS).
- Default port: `8091`. Overridable via `METADATA_EMULATOR_PORT`.
- Required request header: `Metadata-Flavor: Google` (403 otherwise).
- All responses carry `Metadata-Flavor: Google`.

## Module layout

| File | Responsibility |
|---|---|
| `__init__.py` | Re-exports `MetadataService`. |
| `service.py` | `MetadataService` — `start`/`stop`/`health`/`reset_state`. Owns the uvicorn server task. |
| `app.py` | `build_app()` factory. Defines `MetadataFlavorMiddleware` and every route. Reads configuration from `os.environ` at request time. |
| `tokens.py` | `build_access_token()` returns a `dict`. `build_id_token(*, audience, email, numeric_project_id)` returns a JWT string with a stub signature. Both are pure functions. |

## Request lifecycle

```
client request
  │
  ▼
MetadataFlavorMiddleware
  ├─ no/wrong Metadata-Flavor header   → 403 PlainTextResponse (+ Metadata-Flavor: Google)
  └─ header OK
       │
       ▼
   FastAPI route handler
       │
       ▼
   read env-var-backed config (_email(), _project_id(), _numeric_project_id(), _scopes())
       │
       ▼
   for /token  → build_access_token() → JSON
   for /identity → check audience param → build_id_token(...) → text/plain JWT
   for scalar paths (/email, /project-id, ...) → PlainTextResponse
   for /{alias}/ recursive view → JSON
       │
       ▼
   MetadataFlavorMiddleware stamps Metadata-Flavor: Google on the response
```

## Error mapping

| Condition | HTTP status | Body |
|---|---|---|
| Missing `Metadata-Flavor: Google` request header | `403` | `Missing required Metadata-Flavor header.` |
| `/identity` with no `?audience=` or empty audience | `400` | `non-empty audience parameter required` |
| Unknown `{alias}` (not `default` or `$METADATA_SERVICE_ACCOUNT_EMAIL`) | `404` | `alias not found` |
| Any other path under `/computeMetadata/v1/` | `404` | (FastAPI default) |

## Configuration source

All variables are read from `os.environ` per request (except `METADATA_EMULATOR_PORT`, which is read once at `MetadataService.start()`). This means you can `kubectl set env` a running pod for the *client*, but the *server* would need a restart to change the bound port — which matches the constraint that ports can't be rebound at request time.

## Token shape

### Access token

```json
{
  "access_token": "ya29.gcp-local-stub-token",
  "expires_in":   3600,
  "token_type":   "Bearer"
}
```

The `ya29.` prefix matches Google's real access-token format so the value is recognizable in logs. The string is fixed; nothing downstream validates it on the emulator path.

### ID token (JWT)

`header.payload.signature`, all base64url-encoded.

```
header:    {"alg":"RS256","kid":"gcp-local-stub","typ":"JWT"}
payload:   {
             "iss":            "https://accounts.google.com",
             "aud":            "<audience-from-?audience=>",
             "sub":            "$METADATA_NUMERIC_PROJECT_ID",
             "azp":            "$METADATA_SERVICE_ACCOUNT_EMAIL",
             "email":          "$METADATA_SERVICE_ACCOUNT_EMAIL",
             "email_verified": true,
             "iat":            <now>,
             "exp":            <now + 3600>
           }
signature: base64url("gcp-local-stub-signature")
```

Libraries that decode the JWT to inspect `aud` (IAP / OIDC client code) get the right audience. Libraries that verify the signature against Google's JWKS get a clean verification failure.

## Tests

- `tests/unit/services/metadata/test_tokens.py` — pure-function tests for both builders, including JWT round-trip parse + claim checks.
- `tests/unit/services/metadata/test_app.py` — routes via `httpx.AsyncClient`. Covers every row of the endpoint contract: happy paths, `Metadata-Flavor` enforcement, env-var overrides, unknown alias → 404, missing audience → 400.
- `tests/unit/services/metadata/test_service.py` — registry discovery + uvicorn lifecycle. Verifies `start` binds the port, `stop` unbinds, `health` reflects the state machine, `reset_state` is a no-op.
- `tests/integration/test_metadata_integration.py` — real `google-auth`:
  - `ComputeEngineCredentials.refresh()` succeeds and the credentials carry the stub token.
  - `google.auth.default()` returns `ComputeEngineCredentials` and the configured project.
  - `IDTokenCredentials` produces a JWT whose `aud` claim matches the requested target.
  - `bigquery.Client()` with no `AnonymousCredentials` and no `client_options` runs a query end-to-end. **This is the headline regression test.**

## Internals-level limitations

- **No signed tokens.** Stub strings. Adding RSA signing would let downstream code verify the JWT, but no consumer requests this today.
- **Single SA.** Only `default` and the configured email alias are served; arbitrary attached SAs are deferred.
- **No request retries / rate limits.** This is local-only software.
- **Port read once at startup.** Other config is request-time-read; port is bound once.
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture/metadata.md
git commit -m "docs(metadata): add architecture doc"
```

---

## Task 16: README and deployment doc updates

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Update the README services-at-a-glance table**

Open `README.md`. Find the "Services at a glance" table (around line 53). The columns are: `Service | Status | Default port | Wire | Usage | Architecture`. Append a new row after the `Firestore` row:

```markdown
| Metadata server | Alpha | 8091 | REST | [usage](docs/services/metadata.md) | [internals](docs/architecture/metadata.md) |
```

- [ ] **Step 2: Update `docs/deployment.md` default-ports table**

Open `docs/deployment.md`. Find the "Default ports" table (around line 7-16). Add a new row after the Firestore row:

```markdown
| Metadata server | 8091 | HTTP; clients honor `GCE_METADATA_HOST=<host>:8091` |
```

- [ ] **Step 3: Add an explanatory paragraph after the ports table**

Immediately after the default-ports table in `docs/deployment.md`, before the "Building the image" heading, insert:

```markdown
### Metadata server (opting out of `AnonymousCredentials`)

The metadata server emulates GCE/GKE's `metadata.google.internal` endpoint so unmodified ADC client code — `bigquery.Client()` with no arguments — can mint a stub token and route subsequent traffic through the rest of `gcp-local`. To use it from a pod, set `GCE_METADATA_HOST` (and `GCE_METADATA_IP`) to the gcp-local hostname:port alongside the per-service `*_EMULATOR_HOST` variables you already set. See [`docs/services/metadata.md`](services/metadata.md) for a copy-pasteable manifest.

To run without the metadata server: `SERVICES=gcs,bigquery,pubsub,firestore,secret_manager`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/deployment.md
git commit -m "docs(metadata): README services row + deployment ports row"
```

---

## Task 17: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Lint clean**

Run: `ruff check src/ tests/`
Expected: zero issues.

If any fire, fix them inline (most likely: import order, unused variables in test files).

- [ ] **Step 2: Format clean (matches CI's repo-wide check)**

Run: `ruff format --check .`
Expected: zero files need reformatting.

If any do: run `ruff format .` and commit the result with `chore: ruff format`.

- [ ] **Step 3: Type check clean**

Run: `mypy src/`
Expected: zero issues.

- [ ] **Step 4: Full unit + integration suite**

Run: `pytest tests/ --ignore=tests/integration/test_docker_image.py -v`
Expected: all green. Existing tests untouched by metadata service should still pass.

- [ ] **Step 5: Docker image smoke test**

Build and verify the image still healthy with the metadata service running:

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
docker run --rm -d --name gcp-local-smoke \
  -p 4510:4510 -p 8091:8091 \
  gcp-local:dev
sleep 2
curl -fsS http://localhost:4510/_emulator/health
curl -fsS -H "Metadata-Flavor: Google" http://localhost:8091/computeMetadata/v1/project/project-id
docker stop gcp-local-smoke
```

Expected: admin health is JSON `{"ok": true, ...}` listing `metadata` among the services; metadata `project-id` endpoint returns `local-dev` (or whatever `$GOOGLE_CLOUD_PROJECT` resolves to in the container, default `local-dev`).

- [ ] **Step 6: Walk the Definition of Done audit**

Open `CLAUDE.md` and walk both the docs and tests audit checklists for this PR. Confirm:

- `docs/services/metadata.md` exists (new user-facing doc).
- `docs/architecture/metadata.md` exists (new internals doc).
- `README.md` services table has a new row.
- `docs/deployment.md` has new row + paragraph.
- `ROADMAP.md` no change (feature wasn't roadmapped).
- `CHANGELOG.md` no change (auto-generated by release-please).
- `pyproject.toml` updated (entry point added).
- Unit tests cover every endpoint and lifecycle method.
- Integration tests cover the four ADC paths (refresh, default, id-token, BQ-with-plain-ADC).
- Error paths covered (403 without header, 400 without audience, 404 unknown alias).

- [ ] **Step 7: Final commit (only if Step 2 reformatted anything)**

If `ruff format` touched anything in Step 2, the commit was already created there. Otherwise no commit needed.

- [ ] **Step 8: Push and open PR**

```bash
git push -u origin feat/metadata-server
gh pr create --title "feat(metadata): fake GCE metadata server for unmodified ADC clients" --body "$(cat <<'EOF'
## Summary
- New `metadata` service emulates the GCE/GKE metadata server so unmodified ADC client code can talk to gcp-local without `AnonymousCredentials`.
- Serves `/token`, `/identity`, `/email`, `/scopes`, project ID endpoints under `/computeMetadata/v1/`.
- Default port `8091`. Default-on (part of `SERVICES=all`); opt out via `SERVICES=gcs,bigquery,...`.
- Stub access token (`ya29.gcp-local-stub-token`) and real-format JWT with a placeholder signature for ID tokens.

## Test plan
- [ ] `pytest tests/unit/services/metadata/` green (token builders, routes, lifecycle).
- [ ] `pytest tests/integration/test_metadata_integration.py` green (google-auth refresh, google.auth.default, id-token audience, BigQuery with plain ADC).
- [ ] `pytest tests/integration/test_core_end_to_end.py` still green (metadata service registered alongside others without conflict).
- [ ] `ruff check`, `ruff format --check`, `mypy src/` clean.
- [ ] Docker build healthy with `-p 8091:8091`.

Spec: `docs/superpowers/specs/2026-05-18-metadata-server-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

Plan covers every spec section:

| Spec section | Task(s) |
|---|---|
| Goal #1 (Metadata-Flavor handshake) | 4 |
| Goal #2 (access token) | 7 |
| Goal #3 (ID token) | 8 |
| Goal #4 (email/scopes/project/numeric-project) | 5, 6 |
| Architecture (package layout, lifecycle) | 1, 9 |
| Endpoint contract (all rows) | 4, 5, 6, 7, 8 |
| Token shape | 2, 3 |
| Configuration | 5, 6 (env-var tests) |
| Error handling (403/400/404) | 4, 8, 6 |
| Testing (unit + integration) | 2–12 (unit), 11–13 (integration) |
| Docs surfaces | 14, 15, 16 |
| Acceptance criteria | covered by integration tests + Task 17 docker smoke |

No placeholders, no TODOs, every step has either code or a concrete command. Type signatures referenced in later tasks (`build_access_token`, `build_id_token`, `MetadataService`, `build_app`) all match what earlier tasks defined.
