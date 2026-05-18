# GCE metadata server — design

**Status:** approved (brainstorm 2026-05-18)
**Closes roadmap follow-up:** none — net-new feature.

## Context

Today, every documented way to use `gcp-local` from Python requires the client code to pass `google.auth.credentials.AnonymousCredentials()` and an explicit `client_options.api_endpoint`. This is fine for code written for the emulator, but it forces a fork between local code and production code: production runs on GKE with Workload Identity and uses unmodified ADC (`bigquery.Client()` with no arguments); local runs against `gcp-local` and must monkey-patch credentials.

Workload Identity on GKE works by routing requests for `metadata.google.internal` to a node-local server that hands out short-lived bearer tokens. `google-auth`'s ADC chain picks `ComputeEngineCredentials` when it can reach that server, fetches a token, and attaches it to every outbound API call. The cloud-service backends ignore token *values* on the emulator path — the only thing the emulator can't currently satisfy is the auth-time **handshake** that decides credential type.

A small fake GCE metadata server inside `gcp-local` removes the fork. Unmodified client code with `GCE_METADATA_HOST` set finds `ComputeEngineCredentials`, mints a stub token, and proceeds — exactly the production code path, with the cloud-service traffic still routed to the emulator via the existing `*_EMULATOR_HOST` env vars.

## Goal

Ship an opt-out (default-on, like every other service) HTTP service that speaks enough of the GCE metadata protocol for `google-auth`-based clients to:

1. Detect a metadata server via the `Metadata-Flavor` header handshake.
2. Mint a stub access token via `/computeMetadata/v1/instance/service-accounts/default/token`.
3. Mint a stub ID token via `/computeMetadata/v1/instance/service-accounts/default/identity?audience=...`.
4. Read the configured service-account email, scopes, project ID, and numeric project ID.

The service runs alongside the existing services, registered through the same entry-point group, with no changes to the `Service` protocol or the registry.

## Non-goals (deferred)

- **Signed tokens.** The access token is a fixed `"ya29.gcp-local-stub-token"` string; the ID token is a real-format JWT with a placeholder signature that won't verify against Google's JWKS. The emulator services ignore token values, so this is enough. Adding RSA signing would let downstream code verify the JWT, but no consumer requests this today.
- **Multi-SA aliases.** Only `default` and the configured email-as-alias are served. Real GCE supports arbitrary attached service accounts. YAGNI for the local-dev use case.
- **Non-`default` paths under `/computeMetadata/v1/`.** No `/instance/zone`, `/instance/name`, `/instance/id`, `/instance/attributes/*`, `/instance/network-interfaces/*`. These are used by infrastructure tooling rather than client libraries and add surface without value.
- **`metadata.google.internal` resolution.** The service binds on a regular port. Pointing the magic hostname at it is the user's k8s / docker problem (CoreDNS rewrite, `hostAliases`, sidecar on `127.0.0.1`); we just document the options.
- **TLS.** All emulator endpoints are plain HTTP; the metadata server matches.
- **State persistence.** No state to persist. `reset_state` is a no-op.

## Architecture

### Package layout

```
src/gcp_local/services/metadata/
├── __init__.py     # re-exports MetadataService
├── service.py      # Service-protocol lifecycle (start/stop/health/reset_state)
├── app.py          # FastAPI app factory + all routes
└── tokens.py       # build_access_token(), build_id_token(audience, email, ...)
```

Registered in `pyproject.toml`:

```toml
[project.entry-points."gcp_local.services"]
metadata = "gcp_local.services.metadata:MetadataService"
```

No changes to `Service`, `Context`, `ServiceRegistry`, or `Lifecycle`. The service inherits the same toggling behavior every other service has (`SERVICES=all`, `SERVICES=gcs,bigquery,metadata`, `METADATA_EMULATOR_PORT=...`).

### Components

| Component | Responsibility |
|---|---|
| `MetadataService` (`service.py`) | Holds the uvicorn server, binds the port, implements `start`/`stop`/`health`/`reset_state`. Logs at startup the value that clients must put in `GCE_METADATA_HOST`. |
| FastAPI app (`app.py`) | Routes under `/computeMetadata/v1/`. Middleware enforces `Metadata-Flavor: Google` on requests and stamps it on responses. Reads configuration (email, project, scopes, numeric ID) from `os.environ` at request time so changes take effect without restart. |
| `tokens.py` | Pure functions. `build_access_token()` returns a `{"access_token", "expires_in", "token_type"}` dict. `build_id_token(audience, email, numeric_project_id)` returns a base64url-encoded `header.payload.signature` JWT string. |

Nothing is stateful: no `storage.py`, no `engine/`, no `models.py`, no `names.py`, no `errors.py` module. Errors are raised inline as `fastapi.HTTPException`.

### Data flow

```
[ client pod / process ]
  google-auth (ADC) — GCE_METADATA_HOST=<host>:8091
                      OR DNS rewrite of metadata.google.internal
        │
        ▼
[ MetadataService :8091 ]  ── FastAPI route ──►  build_access_token / build_id_token
        │                                              │
        └──── response: bearer token / JWT  ◄──────────┘
  google-auth attaches "Authorization: Bearer ya29.gcp-local-stub-token"
        │
        ▼
[ BigQuery / GCS / PubSub / Firestore / Secret Manager service ]
  emulator ignores the token, processes the request
```

Two key properties:

1. **Stateless.** Each request is computed from env vars + the request itself. No cross-request memory.
2. **No coupling to other services.** It does not publish to `StateHub` or call any sibling service. It is a leaf.

## Endpoint contract

All routes under `/computeMetadata/v1/`. Every request **must** include header `Metadata-Flavor: Google` — real GCE returns `403` without it, and `google-auth` always sends it. Every response includes header `Metadata-Flavor: Google` — `google-auth` checks this when probing.

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/` | `200`, `text/plain` body `"computeMetadata/\n"` | Probe path. |
| `GET` | `/computeMetadata/v1/` | `200`, `application/json` when `?recursive=true`, else `text/plain` newline-listing of children. | |
| `GET` | `/computeMetadata/v1/instance/service-accounts/` | `200`, `text/plain` `"default/\n<configured-email>/\n"` | |
| `GET` | `/computeMetadata/v1/instance/service-accounts/{alias}/` | `200`, `application/json` recursive view: `{"aliases": ["default"], "email": "...", "scopes": [...]}`. `{alias}` ∈ `{"default", "<configured-email>"}`; otherwise `404`. | |
| `GET` | `/computeMetadata/v1/instance/service-accounts/{alias}/email` | `200`, `text/plain`, the configured email. | |
| `GET` | `/computeMetadata/v1/instance/service-accounts/{alias}/scopes` | `200`, `text/plain`, one scope per line. | |
| `GET` | `/computeMetadata/v1/instance/service-accounts/{alias}/token` | `200`, `application/json` `{"access_token": "...", "expires_in": 3600, "token_type": "Bearer"}`. `?scopes=` query param accepted and ignored. | |
| `GET` | `/computeMetadata/v1/instance/service-accounts/{alias}/identity` | `200`, `text/plain`, JWT string. **Requires `?audience=`** — `400` otherwise. | |
| `GET` | `/computeMetadata/v1/project/project-id` | `200`, `text/plain`, configured project ID. | |
| `GET` | `/computeMetadata/v1/project/numeric-project-id` | `200`, `text/plain`, configured numeric project ID. | |
| any | other paths under `/computeMetadata/v1/` | `404`, `text/plain` | Catch-all. |

## Token shape

### Access token

```json
{
  "access_token": "ya29.gcp-local-stub-token",
  "expires_in":   3600,
  "token_type":   "Bearer"
}
```

The `ya29.` prefix matches Google's real access-token format so the value is recognizable in logs. The string is fixed; nothing downstream validates it on the emulator path. If the token accidentally reaches real Google, the request fails cleanly with `401`.

### ID token

A real-format JWT — `header.payload.signature`, base64url-encoded — with a stub signature.

```
header:    {"alg":"RS256","kid":"gcp-local-stub","typ":"JWT"}
payload:   {
             "iss":            "https://accounts.google.com",
             "aud":            "<audience-from-query>",
             "sub":            "<configured numeric-project-id>",
             "azp":            "<configured email>",
             "email":          "<configured email>",
             "email_verified": true,
             "iat":            <now seconds>,
             "exp":            <now seconds + 3600>
           }
signature: base64url("gcp-local-stub-signature")
```

Libraries that decode the JWT to inspect `aud` (common in IAP / OIDC client code) get the right audience. Libraries that verify the signature against Google's JWKS get a clean verification failure — which is the same failure they would hit if they accidentally pointed at the emulator in production.

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `METADATA_EMULATOR_PORT` | `8091` | Port to bind. Matches the `<NAME>_EMULATOR_PORT` convention shared by every other service. |
| `METADATA_SERVICE_ACCOUNT_EMAIL` | `default@local-dev.iam.gserviceaccount.com` | Value of `/email`, `email`/`azp` claims in the ID token, second alias under `/instance/service-accounts/`. |
| `GOOGLE_CLOUD_PROJECT` | `local-dev` | Value of `/project/project-id`. Intentionally reuses the standard Google env var — most clients already set it. |
| `METADATA_NUMERIC_PROJECT_ID` | `0` | Value of `/project/numeric-project-id` and the `sub` claim. |
| `METADATA_SCOPES` | `https://www.googleapis.com/auth/cloud-platform` | Comma-separated. Returned newline-joined from `/scopes` and as a list in the recursive view. |

`METADATA_EMULATOR_PORT` is read once at `start()` (the port is bound for the lifetime of the service). The remaining four variables are read at request time — change the env var, the next response reflects it, no restart.

## Error handling

| Condition | Response | Why |
|---|---|---|
| Missing `Metadata-Flavor: Google` request header | `403`, `text/plain` `"Missing required Metadata-Flavor header."` | Matches real GCE. `google-auth` uses the header round-trip to verify the server is genuine. |
| `/identity` without `?audience=` query param | `400`, `text/plain` `"non-empty audience parameter required"` | Matches real GCE. Without this, `google-auth` would silently produce an unbound ID token. |
| Unknown `{alias}` (not `default` or configured email) | `404`, `text/plain` | Surfaces typos rather than returning wrong data. |
| Any other path under `/computeMetadata/v1/` | `404`, `text/plain` | Catch-all. |
| Port in use at startup | Raised in `MetadataService.start()`; `Lifecycle` records the failure | Same path other services already use. |

No retries, no rate limits, no input validation beyond the above. Token generation is pure formatting and cannot fail.

## Testing

### Unit tests (`tests/unit/services/metadata/`)

- `test_app.py` — `httpx.AsyncClient` against the FastAPI app:
  - happy path for each row of the endpoint contract table
  - `Metadata-Flavor` enforcement (request rejected without it, response always carries it)
  - `/identity` without `?audience=` → `400`
  - unknown alias → `404`
  - env-var override takes effect on the next request (set env, hit endpoint, assert returned value reflects the override without restart)
- `test_tokens.py`:
  - `build_access_token` returns the documented shape
  - `build_id_token` output is a parseable JWT; claims are `aud`, `iss`, `email`, `azp`, `sub`, `email_verified`, `iat`, `exp`; `exp > iat`
- `test_service.py`:
  - `start`/`stop` bind and release the port
  - `health` reports `ok=False` before start, `ok=True` after, `ok=False` after stop
  - `reset_state` is a no-op (does not raise, does not unbind)

### Integration test (`tests/integration/test_metadata_integration.py`)

This is the value-proposition test. It drives real `google-auth` end-to-end.

- `test_compute_engine_credentials_refresh_against_emulator` — points `GCE_METADATA_HOST` at the emulator port, instantiates `google.auth.compute_engine.Credentials()`, calls `.refresh()`, asserts the credentials carry the stub token and the configured email.
- `test_google_auth_default_picks_metadata_server` — clears all other ADC sources (`GOOGLE_APPLICATION_CREDENTIALS`, gcloud config dir), calls `google.auth.default()`, asserts it returns `ComputeEngineCredentials`.
- `test_id_token_from_metadata_server_has_correct_audience` — fetches an ID token via the metadata server, decodes (without verifying signature), asserts the `aud` claim matches what was requested.
- `test_bigquery_client_works_with_adc_only` — the headline test. With `GCE_METADATA_HOST` and `BIGQUERY_EMULATOR_HOST` both pointed at the in-process emulator, instantiates `bigquery.Client(project="local-dev")` (no `AnonymousCredentials`, no `client_options`), runs `SELECT 1`, asserts the result. This is the regression test for "unmodified ADC code talks to gcp-local."

### Quality gates

- `ruff check src/ tests/` clean
- `ruff format --check src/ tests/` clean
- `pytest tests/ --ignore=tests/integration/test_docker_image.py` green
- Docker build + container health check still green when the metadata service is included.

## Documentation surfaces

Per the Definition of Done in `CLAUDE.md`, every PR walks both audit checklists. For this feature:

| File | Change |
|---|---|
| `docs/services/metadata.md` *(new)* | User-facing guide. Elevator pitch; what's emulated; what's not; how clients reach it from k8s pods (env-var snippet for `GCE_METADATA_HOST` plus the `*_EMULATOR_HOST` set), from docker-compose, and from a host shell; worked example with `google-cloud-bigquery` using plain ADC; limits & quirks. |
| `docs/architecture/metadata.md` *(new)* | Internals: endpoint contract, token shape, configuration, request lifecycle, error mapping, tests. |
| `README.md` services-at-a-glance table | New row: `metadata` / port 8091 / Alpha. Links to both docs. |
| `docs/deployment.md` default-ports table | New row for port 8091. Short paragraph after the table explaining `GCE_METADATA_HOST` and why this lets app code drop `AnonymousCredentials`. |
| `ROADMAP.md` | No change — feature was not previously roadmapped. |
| `CHANGELOG.md` | Not edited by hand; release-please generates it from the Conventional Commit subjects. |
| `docs/development/adding-a-service.md` | No change; this service follows the existing template. |

The user-facing page `docs/services/metadata.md` is load-bearing: that's where "how do I use this from my pod" gets answered, with a copy-pasteable env-var block and a Python snippet that imports zero auth-related symbols.

## Acceptance criteria

The feature is done when all of the following hold:

1. `SERVICES=all` (the default) starts the metadata server alongside the others.
2. `SERVICES=gcs,bigquery` does **not** start the metadata server.
3. `METADATA_EMULATOR_PORT=8888` rebinds the metadata server to 8888.
4. With `GCE_METADATA_HOST` pointed at the metadata server, `google.auth.default()` returns `ComputeEngineCredentials` and `.refresh()` succeeds.
5. With `GCE_METADATA_HOST` and `BIGQUERY_EMULATOR_HOST` both pointed at `gcp-local`, the snippet
   ```python
   from google.cloud import bigquery
   bq = bigquery.Client(project="local-dev")
   list(bq.query("SELECT 1 AS x").result())
   ```
   succeeds with no `AnonymousCredentials`, no `client_options`, no Google-auth-related imports.
6. `METADATA_SERVICE_ACCOUNT_EMAIL=maestro-evals@algo-agents-ai21.iam.gserviceaccount.com` makes `/email` return that string and the ID-token `email` claim carry that string.
7. `/computeMetadata/v1/instance/service-accounts/default/identity` without `?audience=` returns `400`.
8. Every request without `Metadata-Flavor: Google` returns `403`; every response carries `Metadata-Flavor: Google`.
9. `docs/services/metadata.md`, `docs/architecture/metadata.md`, README and `docs/deployment.md` exist and link consistently.
10. `ruff check`, `ruff format --check`, full `pytest` suite (excluding Docker image test) are green locally and in CI.
