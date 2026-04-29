# Roadmap

This document tracks what's actively being built, what's committed to v1, and what's likely post-v1. Implemented services live in the [README](README.md#services-at-a-glance) table; this file is forward-looking.

Status vocabulary:

- **Stable** — feature-complete for v1 scope, no breaking changes expected.
- **Alpha** — implemented and in use, but API surface or internals may shift.
- **Planned** — committed to v1 roadmap, not started yet.
- **Future** — not on the v1 roadmap; would be considered post-v1.

## In progress

| Service | Owner | Started | Tracking |
|---|---|---|---|

(empty — nothing is currently in progress.)

## Planned (v1)

These services are committed to the v1 roadmap. The order is rough; pick whichever you'd like to contribute.

| Service | Wire | Default port | Default env var | Notes |
|---|---|---|---|---|
| Pub/Sub | gRPC | 8085 | `PUBSUB_EMULATOR_HOST` | Topics, subscriptions, push delivery |
| Firestore | gRPC | (TBD) | `FIRESTORE_EMULATOR_HOST` | Documents, queries, indexes |

## Future (post-v1)

These are services we know we'll want eventually but haven't committed to. The list is not exhaustive — anything not listed simply hasn't been considered yet.

| Service | Wire | Default port | Default env var | Notes |
|---|---|---|---|---|
| Cloud Functions | HTTP | (TBD) | (none) | Local function execution |
| Cloud Tasks | gRPC / REST | (TBD) | (none) | Queue + leasing semantics |
| Cloud Spanner | gRPC | (TBD) | `SPANNER_EMULATOR_HOST` | Strong consistency, SQL surface |

## Per-service follow-ups

These are known gaps in the already-implemented (Alpha) services, tracked here so they don't get lost.

### BigQuery

- **`maxBadRecords` / `ignoreUnknownValues`** on load jobs — currently accepted but treated as all-or-nothing; correct semantics need partial-row tolerance.
- **CSV cell coercion for DATE / TIMESTAMP / JSON columns** — currently pass-through; relies on DuckDB implicit cast.
- **`statistics.totalBytesProcessed`** — always reports `0`; DuckDB doesn't expose an equivalent metric.
- **Parquet / Avro / ORC source formats** for load jobs.

### GCS

See the "What's not emulated" section of [`docs/services/gcs.md`](docs/services/gcs.md) for the full user-facing list. Internals-level follow-ups:

- HMAC keys, retention policies, object lock, customer-supplied encryption keys are not implemented.
- Signed URLs are accepted-and-ignored — no signature validation.
- Cross-service notifications (`gcs.object.finalize` etc. published to the StateHub) have no external delivery yet.

### Secret Manager

- **IAM** (`SetIamPolicy` / `GetIamPolicy` / `TestIamPermissions`) — currently return `UNIMPLEMENTED`. A future increment can add accept-and-store semantics.
- **Replication policy enforcement** — `automatic` and `user_managed` accepted, not enforced.
- **CMEK** — accepted, not enforced.
- **Rotation schedules** — not implemented.
- **Audit logging** — not emitted.

## How to update this file

When a Planned service starts being built, move the row to `In progress` and fill `Owner` / `Started` / `Tracking`. When it ships, delete the row entirely — implemented services live in the [README](README.md#services-at-a-glance) table, not here.

When a follow-up gap is closed, delete the bullet from the corresponding `Per-service follow-ups` subsection.

The PR template (`.github/pull_request_template.md`) and the contributor checklist ([`docs/development/adding-a-service.md`](docs/development/adding-a-service.md)) both call out these updates explicitly.
