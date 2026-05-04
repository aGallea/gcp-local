# GCS — internals

## At a glance

The GCS service is a pure REST emulator of the Google Cloud Storage JSON API v1. It is built on FastAPI + uvicorn and runs inside the same process as every other gcp-local service. Two storage backends are available: an all-in-memory backend (the default) and an on-disk backend that is activated when `PERSIST=1` is set. Neither backend depends on DuckDB; the GCS layer has no SQL component. Generation and metageneration counters are first-class concepts, tracked per object, and are used by the conditional-request machinery (`If-Match` / `If-None-Match` style preconditions). State-hub events are emitted on every mutation so that future cross-service consumers (e.g., BQ load jobs) can subscribe without polling.

For usage — client configuration, bucket/object CRUD examples, resumable upload guidance, and known gaps — see [`docs/services/gcs.md`](../services/gcs.md). This document covers implementation internals.

---

## Wire & port

The service listens on **port 4443** (the same default as `fake-gcs-server`), which pairs directly with `STORAGE_EMULATOR_HOST=http://localhost:4443`. The port can be overridden via the core's `Settings.port_overrides` mechanism. The admin/health port follows the standard gcp-local pattern on **4510**. No TLS is used; the emulator is local-only.

---

## Storage model

Both backends implement the `GcsStorage` Protocol defined in `storage.py`. The service layer is entirely storage-agnostic; the choice of backend is made once in `GcsService._make_storage()` at startup.

**In-memory backend (`InMemoryStorage`):** Three top-level dicts hold all state.

- `_buckets: dict[str, BucketMeta]` — keyed by bucket name.
- `_objects: dict[tuple[str, str], tuple[ObjectRecord, bytes]]` — keyed by `(bucket_name, object_name)`. The tuple stores both the metadata record and the raw bytes together.
- `_sessions: dict[str, tuple[UploadSession, bytearray]]` — keyed by session ID; the bytearray accumulates chunks in-place.

Per-bucket `asyncio.Lock` instances (in `_locks`) guard mutations. Reads take no lock.

**Disk backend (`DiskStorage`):** Activated when `PERSIST=1`. Root is `<data_dir>/gcs/`. Layout under the root:

```
<bucket>/
  <bucket>.meta.json          # BucketMeta JSON
  objects/
    <object_name>             # raw bytes (may be nested under subdirs for slash-delimited names)
    <object_name>.meta.json   # ObjectRecord JSON sidecar
  .uploads/
    <session_id>/
      buffer.bin              # accumulated chunk bytes
      session.json            # UploadSession JSON
```

Object files are written atomically under a per-bucket `asyncio.Lock`. A collision guard (`_ensure_no_collision`) enforces the invariant that an object file and a directory cannot occupy the same path — attempting to write `foo/bar` when a plain file `foo` already exists returns `409 Conflict`.

Stale upload sessions (older than 7 days by directory mtime) are garbage-collected at service startup via `DiskStorage.gc_stale_sessions()`.

---

## Object representation

Each stored object carries the following fields (defined in `models.ObjectRecord`):

| Field | Notes |
|---|---|
| `bucket`, `name` | identity |
| `size` | byte length of the payload |
| `generation` | monotonically increasing per bucket; assigned by `GenerationCounter` |
| `metageneration` | starts at 1; incremented on metadata-only `PATCH` |
| `content_type` | defaults to `application/octet-stream` |
| `content_encoding`, `content_language`, `content_disposition`, `cache_control` | standard HTTP headers, default empty |
| `md5_hash` | base-64 MD5 of the payload bytes (server-computed) |
| `crc32c` | base-64 CRC32C via `google-crc32c` (server-computed) |
| `time_created` | RFC3339 timestamp; frozen at first write, not reset on overwrite |
| `updated` | RFC3339 timestamp; updated on every write and on metadata PATCH |
| `metadata` | `dict[str, str]` — user-controlled key/value pairs (`x-goog-meta-*`) |
| `etag` | computed field: `"<generation>/<metageneration>"` |

The JSON shape returned by every object API response. Note that
`generation`, `metageneration`, and `size` are wire-serialized as JSON
**strings** even though they hold integer values — the GCS JSON API spec
declares them as `int64`/`uint64` with `json:",string"` tags, and Go
clients (e.g. Argo Workflows' executor, `cloud.google.com/go/storage`)
reject raw JSON numbers. Internally they are stored as `int` on
`ObjectRecord`; the coercion lives in `models.py` via `@field_serializer`.

```json
{
  "bucket": "my-bucket",
  "name": "logs/2026/04/app.log",
  "generation": "17",
  "metageneration": "1",
  "size": "1234",
  "contentType": "text/plain",
  "md5Hash": "<base64>",
  "crc32c": "<base64>",
  "etag": "\"17/1\"",
  "timeCreated": "2026-04-24T10:30:00.000000Z",
  "updated": "2026-04-24T10:30:00.000000Z",
  "metadata": {"user-key": "user-value"}
}
```

---

## Request lifecycle: simple upload

Simple uploads use `uploadType=media` (single-chunk, raw body) or `uploadType=multipart` (raw body bundled with metadata in a `multipart/related` envelope). Both are handled by `register_upload_routes()` in `routes/uploads.py` via `POST /upload/storage/v1/b/{bucket}/o`.

For `uploadType=media`:
1. Route extracts the object name from the `name` query parameter and reads the raw request body.
2. Preconditions (`ifGenerationMatch`, `ifGenerationNotMatch`, `ifMetagenerationMatch`, `ifMetagenerationNotMatch`) are parsed from query parameters and passed to `_finalize_object()`.
3. `_finalize_object()` fetches the current object record (if any) from storage, runs `evaluate_preconditions()`, then builds an `ObjectRecord` with a new generation from `GenerationCounter.next(bucket)`, computes MD5 and CRC32C from the payload bytes, calls `storage.put_object()`, and publishes `gcs.object.finalize` to the state hub.
4. The route returns `200 OK` with the full `ObjectRecord` as JSON.

For `uploadType=multipart`, the request body is parsed by `_parse_multipart()` (using Python's `email.parser`): part 1 carries application/json metadata (object name, `contentType`, user `metadata`), part 2 carries the raw bytes. The combined metadata and bytes flow through the same `_finalize_object()` path.

---

## Resumable uploads

Resumable uploads use `uploadType=resumable` and are handled in two stages.

**Initiation (`POST /upload/storage/v1/b/{bucket}/o?uploadType=resumable`):**
The route reads optional JSON body fields (`name`, `contentType`, `metadata`) and the `x-upload-content-length` header (total size, optional). It allocates a URL-safe 128-bit random session ID via `ids.new_session_id()`, creates an `UploadSession` record with `bytes_received=0`, and persists it via `storage.put_session()`. The response carries a `Location` header:
```
http://<host>/upload/storage/v1/b/{bucket}/o?upload_id=<session-id>
```

**Chunk upload (`PUT /upload/storage/v1/b/{bucket}/o?upload_id=<session-id>`):**
Each PUT carries a `Content-Range: bytes N-M/total` header (or `bytes N-M/*` when total is not yet known). The route validates that `N == session.bytes_received` (contiguous writes only), appends the chunk body via `storage.append_to_session()`, and determines whether the upload is complete:

- **Incomplete:** returns `308 Resume Incomplete` with `Range: bytes=0-<last_received>`.
- **Complete:** calls `_finalize_object()` with the full accumulated bytes, deletes the session, and returns `200 OK` with the full object record.

**Status query:** A PUT with `Content-Range: bytes */*` returns `308` with the current `Range` header without appending data — used by clients to discover where to resume after an interruption.

Sessions older than 7 days are garbage-collected at service start (`DiskStorage.gc_stale_sessions(max_age_seconds=7*86400)`). In-memory sessions have no automatic TTL; they are cleared on `reset_state()`.

---

## Composite operations

Three multi-object routes are registered by `register_copy_compose_routes()` in `routes/copy_compose.py`.

**Copy (`POST /storage/v1/b/{src_bucket}/o/{src_name}/copyTo/b/{dst_bucket}/o/{dst_name:path}`):** Reads the source object bytes and record, creates a new `ObjectRecord` in the destination bucket with a fresh generation (metadata fields from the source, `time_created` reset to now), calls `storage.put_object()`, and publishes `gcs.object.finalize`.

**Compose (`POST /storage/v1/b/{bucket}/o/{name}/compose`):** Accepts a JSON body with a `sourceObjects` array (up to 32 entries, all in the same bucket). Bytes from each source are concatenated in order; MD5 and CRC32C are recomputed over the combined payload. The result is written as a new object with a fresh generation.

**Rewrite:** The `rewriteTo` API surface is not implemented. The spec and `docs/services/gcs.md` document this gap; callers should use `copyTo` instead.

---

## Preconditions

Conditional requests are enforced by `preconditions.py`. The `Preconditions` dataclass holds up to four optional integer fields:

- `if_generation_match` / `if_generation_not_match`
- `if_metageneration_match` / `if_metageneration_not_match`

`evaluate_preconditions(pre, current=<ObjectRecord|None>)` is called before any mutation, receiving the current object state from storage (or `None` if the object does not yet exist). Checks run in this order:

1. `ifGenerationMatch=0` is the "write-if-new" guard — raises `PreconditionFailed` if the object already exists.
2. `ifGenerationMatch=<g>` — raises if current is absent or `current.generation != g`.
3. `ifGenerationNotMatch=<g>` — raises if current exists and `current.generation == g`.
4. `ifMetagenerationMatch=<mg>` — raises if current is absent or `current.metageneration != mg`.
5. `ifMetagenerationNotMatch=<mg>` — raises if current exists and `current.metageneration == mg`.

`PreconditionFailed` is caught by each route handler and translated to `412 conditionNotMet`. Preconditions for resumable uploads are evaluated at session initiation; they are not re-evaluated when the final chunk lands (a known limitation documented in `docs/services/gcs.md`).

---

## Signed URLs

Signed URL support is deliberately absent from the emulator. The emulator makes no attempt to validate `x-goog-signature` parameters or enforce any cryptographic proof of access. If a client presents a URL with signature query parameters (e.g., `X-Goog-Signature`, `x-goog-date`, `X-Goog-Credential`) directed at the emulator host, the emulator accepts the request and ignores those parameters entirely — the URL is treated as an ordinary request.

Generating signed URLs with `blob.generate_signed_url()` requires real GCP credentials and cannot be done against the emulator; this is documented in the usage guide. For local tests, use direct client uploads instead of pre-signed URLs.

---

## Notifications and events

`events.py` defines three string topic constants (`gcs.object.finalize`, `gcs.object.metadata_update`, `gcs.object.delete`) and three async publish helpers (`publish_finalize`, `publish_metadata_update`, `publish_delete`). Each helper calls `StateHub.publish(topic, payload)` where the payload is built by `build_event_payload()` — a dict matching the real GCS object-change notification JSON shape.

Events are published **after** the mutation is durable. The `StateHub` reference is passed in as `hub: StateHub | None`; when `None` (e.g., in isolated unit tests), publishing is a no-op.

Today, the state hub is an internal in-process bus. No external delivery happens. The `events.py` module is the intended hook point for future GCS→BQ load-job wiring: a BQ service subscriber will register on `gcs.object.finalize` and trigger inline-JSON load jobs without any additional plumbing in the GCS layer.

---

## Browser UI consumer

`src/gcp_local/core/ui_api/gcs.py` exposes a small, internal JSON API at `/_emulator/ui-api/v1/buckets/...` that the bundled SPA calls. It is **not** part of the GCS wire contract and clients must not rely on it. Crucially, the ui-api router reads and writes the same `GcsStorage` instance the public REST routes use — there is no shadow state. An upload from `gsutil` is visible in the UI immediately and vice versa.

The UI synthesizes folders from prefix listings (`delimiter=/`) and lets users create empty folders by writing a 0-byte object whose name ends in `/` (e.g. `staging/`). This composes cleanly with `InMemoryStorage`, but `DiskStorage` would otherwise collide with the directory it uses to hold nested-name blobs — `staging/` as a file vs. `staging/` as a directory containing other objects. To resolve the collision, `DiskStorage` URL-encodes the trailing slash on disk: `staging/` is stored at `<bucket>/objects/staging%2F`. The encoding is local to the disk backend; the in-memory representation, the wire JSON, and the ui-api JSON all use the canonical `staging/` name.

For the broader UI architecture (build pipeline, dev loop, recipe for adding a new service surface), see [`docs/development/ui.md`](../development/ui.md).

---

## Errors

All error responses use `errors.error_response()`, which delegates to `gcp_local.core.errors.rest_error_body()`. The resulting JSON envelope matches the GCP standard:

```json
{
  "error": {
    "code": 404,
    "message": "...",
    "errors": [{"domain": "global", "reason": "notFound", "message": "..."}],
    "status": "NOT_FOUND"
  }
}
```

Key HTTP status mappings:

| Scenario | HTTP | reason |
|---|---|---|
| `BucketNotFound` / `ObjectNotFound` | 404 | `notFound` |
| `BucketAlreadyExists` | 409 | `conflict` |
| `ObjectCollision` (dir/file conflict) | 409 | `conflict` |
| `PreconditionFailed` | 412 | `conditionNotMet` |
| `SessionNotFound` | 404 | `notFound` |
| Malformed request / bad params | 400 | `invalid` |
| Range not satisfiable | 416 | `invalid` |

Quota errors are not enforced; there are no rate limits or size caps in the emulator.

---

## Tests

Unit tests live under `tests/unit/services/gcs/` and are organized by concern:

- `test_storage_memory.py` / `test_storage_disk.py` — symmetric backend correctness suites.
- `test_preconditions.py` — each precondition variant including `ifGenerationMatch=0`.
- `test_routes_uploads.py` — simple, multipart, and resumable lifecycle (init, chunks, status query, commit, GC).
- `test_routes_copy_compose.py`, `test_routes_objects_read.py`, `test_routes_objects_write.py`, `test_routes_buckets.py` — per-route handler tests.
- `test_events.py` — state-hub event emission and payload schema.
- `test_ids.py`, `test_models.py`, `test_service_wiring.py` — utility and wiring coverage.

Integration tests in `tests/integration/test_gcs_integration.py` drive the real `google-cloud-storage` Python client library against a live in-process emulator, covering the full CRUD lifecycle, pagination, ranged downloads, preconditions, copy, and compose.

---

## Internals-level limitations

The following gaps are intentional v1 decisions, not oversights.

**No object versioning.** `GenerationCounter` is monotonically increasing, but only the live generation is stored. Previous generations are not retained; there is no way to retrieve a prior version by generation number.

**No IAM / auth.** All requests are accepted unconditionally. `AnonymousCredentials` must be used with the client library; no credential validation is performed.

**No real signature validation.** Signed URL parameters are accepted and silently ignored. The emulator has no key infrastructure.

**Rewrite API absent.** `POST .../rewriteTo/...` is not implemented. Use `copyTo` instead (which is functionally equivalent for emulator use cases).

**No GCS→BQ wiring yet.** `events.py` is in place and publishes `gcs.object.finalize` events, but no BigQuery subscriber is registered. Inline-JSON load jobs are the next planned feature and will hook into this mechanism.

**Resumable preconditions evaluated at initiation only.** A concurrent overwrite between session initiation and final-chunk delivery will not be detected by the precondition check.

**Disk collision restriction.** On `DiskStorage`, an object name that would require a directory to be created where a file already exists (e.g., writing `foo/bar` when `foo` exists as an object) returns `409 Conflict`. Real GCS allows this coexistence; the emulator does not, mirroring `fake-gcs-server`'s resolution.
