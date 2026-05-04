# Roadmap

This document tracks per-service follow-ups and post-v1 work. All five v1 services (BigQuery, GCS, Secret Manager, Pub/Sub, Firestore) are now implemented; the [README](README.md#services-at-a-glance) table lists them with links. This file is forward-looking.

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

All v1 services are now implemented. See the [README](README.md#services-at-a-glance) table for the full list.

## Future (post-v1)

These are services we know we'll want eventually but haven't committed to. The list is not exhaustive — anything not listed simply hasn't been considered yet.

| Service | Wire | Default port | Default env var | Notes |
|---|---|---|---|---|
| Cloud Functions | HTTP | (TBD) | (none) | Local function execution |
| Cloud Tasks | gRPC / REST | (TBD) | (none) | Queue + leasing semantics |
| Cloud Spanner | gRPC | (TBD) | `SPANNER_EMULATOR_HOST` | Strong consistency, SQL surface |

## Browser UI

- **Foundation landed** — a React SPA served at `/ui/` on the admin port (4510), backed by a versioned internal `/_emulator/ui-api/v1/...` namespace. The GCS surface is the v1 pilot (buckets, blobs, folder navigation, upload, preview, download).
- **Per-service follow-ups** — separate specs will add UI surfaces for BigQuery, Secret Manager, Pub/Sub, and Firestore. See [`docs/development/ui.md`](docs/development/ui.md) for the recipe.

## Per-service follow-ups

These are known gaps in the already-implemented (Alpha) services, tracked here so they don't get lost.

### BigQuery

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

### Firestore

- **Listen** — streaming RPC for real-time `on_snapshot()` callbacks. The `firestore.document.written` StateHub event is already emitted on every write; Listen only needs to subscribe to it.
- **Security rules** — `firestore.rules` engine; currently every request is authorized.
- **Composite-index enforcement** — queries currently run regardless of whether a matching index exists; real Firestore returns `FAILED_PRECONDITION` with an index-creation link when an index is missing.
- **Exports / imports / backups** — `FirestoreAdmin.ExportDocuments`, `ImportDocuments`, and all `*Backup*` RPCs currently return `UNIMPLEMENTED`.
- **PartitionQuery** — used by Dataflow and parallel export jobs; currently returns `UNIMPLEMENTED`.
- **Document-history retention** — read-only transactions with `read_time` in the past always see current document state; real Firestore retains a 1-hour history window.
- **Field admin** — `FirestoreAdmin.UpdateField` for TTL field policies and other field-level configuration; currently returns `UNIMPLEMENTED`.

### Pub/Sub

- **Subscription filters** — `filter` is accepted and stored, but every message is delivered regardless.
- **Schema service** — `SchemaService` RPCs not implemented.
- **Snapshots** — `CreateSnapshot` / `Seek(snapshot=...)` return `UNIMPLEMENTED`.
- **BigQuery / Cloud Storage subscriptions** — not supported.
- **Persistence** — Pub/Sub state is in-memory only, even with `PERSIST=1`. Topics, subscriptions, and message backlogs do not survive a restart.
- **Exactly-once delivery** — `enableExactlyOnceDelivery=true` is accepted but downgraded to at-least-once.

## How to update this file

When a Planned service starts being built, move the row to `In progress` and fill `Owner` / `Started` / `Tracking`. When it ships, delete the row entirely — implemented services live in the [README](README.md#services-at-a-glance) table, not here.

When a follow-up gap is closed, delete the bullet from the corresponding `Per-service follow-ups` subsection.

The PR template (`.github/pull_request_template.md`) and the contributor checklist ([`docs/development/adding-a-service.md`](docs/development/adding-a-service.md)) both call out these updates explicitly.
