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
