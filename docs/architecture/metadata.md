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
| `app.py` | `build_app()` factory. Defines `MetadataFlavorMiddleware`, `_resolve_alias`, and every route. Reads configuration from `os.environ` at request time. |
| `tokens.py` | `build_access_token(email)` encodes the SA email into the token and returns a `dict`. `build_id_token(*, audience, email, numeric_project_id)` returns a JWT string with a stub signature. `decode_stub_token_email(token)` reverses the encoding. All are pure functions. |

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

## Alias resolution

`_resolve_alias` in `app.py` handles the `{alias}` path segment:

1. If `alias == "default"`, return `$METADATA_SERVICE_ACCOUNT_EMAIL`.
2. If `alias == $METADATA_SERVICE_ACCOUNT_EMAIL`, return it directly.
3. If `alias` contains `@`, treat it as an email and return it directly (**open alias resolution** — no pre-registration required).
4. Otherwise return `None` → 404.

This means any SA email can be passed as an alias and will receive a token encoding that email, enabling multi-identity IAM testing without emulator configuration changes.

## Error mapping

| Condition | HTTP status | Body |
|---|---|---|
| Missing `Metadata-Flavor: Google` request header | `403` | `Missing required Metadata-Flavor header.` |
| `/identity` with no `?audience=` or empty audience | `400` | `non-empty audience parameter required` |
| Unknown `{alias}` (no `@`, not `default`, not configured email) | `404` | `alias not found` |
| Any other path under `/computeMetadata/v1/` | `404` | (FastAPI default) |

## Configuration source

All variables are read from `os.environ` per request (except `METADATA_EMULATOR_PORT`, which is read once at `MetadataService.start()`). This means you can `kubectl set env` a running pod for the *client*, but the *server* would need a restart to change the bound port — which matches the constraint that ports can't be rebound at request time.

## Token shape

### Access token

```json
{
  "access_token": "ya29.gcp-local-<base64url(email)>",
  "expires_in":   3600,
  "token_type":   "Bearer"
}
```

The `ya29.` prefix matches Google's real access-token format. The suffix encodes the SA email
via URL-safe base64 (no padding). `build_access_token(email)` in `tokens.py` constructs this;
`decode_stub_token_email(token)` reverses it. Emulator services (e.g. Secret Manager with
`SECRET_MANAGER_ENFORCE_IAM=1`) use this to identify the caller without a real auth service.

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
- **No request retries / rate limits.** This is local-only software.
- **Port read once at startup.** Other config is request-time-read; port is bound once.
