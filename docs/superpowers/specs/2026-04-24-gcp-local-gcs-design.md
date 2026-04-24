# gcp-local — GCS Service Design

**Date:** 2026-04-24
**Status:** Draft for review
**Scope:** First real service — Google Cloud Storage (GCS)
**Core design:** [2026-04-24-gcp-local-core-design.md](./2026-04-24-gcp-local-core-design.md)

## 1. Overview

This document specifies the **GCS emulator** — the first real GCP service to plug into the `gcp-local` core framework. It replaces the `DummyService` used to prove the framework end-to-end.

**Success criterion:** running the official `google-cloud-storage` Python client library against the emulator (pointed via `STORAGE_EMULATOR_HOST`) works unchanged for the core developer workflows: creating buckets, uploading objects (simple + resumable), downloading, listing with pagination, deleting, conditional requests based on generation/metageneration, and reading/writing custom metadata.

## 2. Scope (v1)

### In scope

- **Buckets:** create, get, list, delete
- **Objects:** simple upload, resumable upload, multipart upload, download (with HTTP Range), list (pagination + prefix), get metadata, delete, copy, compose (up to 32 sources)
- **Conditional requests:** `ifGenerationMatch`, `ifGenerationNotMatch`, `ifMetagenerationMatch`, `ifMetagenerationNotMatch` on object operations; `ifMetagenerationMatch` / `ifMetagenerationNotMatch` on bucket operations
- **Metadata:** standard fields (`name`, `bucket`, `generation`, `metageneration`, `size`, `contentType`, `contentEncoding`, `contentLanguage`, `contentDisposition`, `cacheControl`, `md5Hash`, `crc32c`, `etag`, `timeCreated`, `updated`) plus the user-controlled `metadata` dict
- **State-hub events** on every object mutation, for future Pub/Sub consumption
- **In-memory and on-disk storage backends** (opt-in via `PERSIST=1`)
- **Write-through durability** — mutating operations persist to disk before responding
- **Dummy service removal** — `src/gcp_local/services/_dummy/` and its entry point are deleted

### Explicitly out of v1 (deferred)

- **Versioning** — generation history preserved across overwrites
- **Signed URLs** — crypto, auth-adjacent; not needed for emulator use
- **IAM / ACLs** — no auth anyway
- **CORS enforcement** — clients don't need this server-side for testing
- **HMAC keys, KMS encryption, requester-pays, retention policies, lifecycle rules**
- **XML API** — the legacy S3-compat surface; `google-cloud-storage` doesn't use it by default
- **Notification config management API** — state-hub emission is in; the API surface for registering/managing notification configs waits for Pub/Sub

## 3. Transport and routing

### 3.1 Listener

- Single REST listener on **port 4443** (matches fake-gcs-server default; pairs naturally with `STORAGE_EMULATOR_HOST=http://localhost:4443`).
- Port is overridable via `GCS_EMULATOR_PORT` env var (already wired through the core's `Settings.port_overrides`).
- FastAPI app, mounted inside a uvicorn server that shares the main process's asyncio event loop.

### 3.2 Routes

Path structure mirrors the GCS JSON API v1:

| Method | Path | Purpose |
|---|---|---|
| GET | `/storage/v1/b` | List buckets |
| POST | `/storage/v1/b` | Create bucket |
| GET | `/storage/v1/b/{bucket}` | Get bucket metadata |
| DELETE | `/storage/v1/b/{bucket}` | Delete bucket |
| GET | `/storage/v1/b/{bucket}/o` | List objects (pagination, prefix, delimiter) |
| GET | `/storage/v1/b/{bucket}/o/{object:path}` | Get object (metadata with `alt=json`; bytes with `alt=media`; ranged with `Range:` header) |
| DELETE | `/storage/v1/b/{bucket}/o/{object:path}` | Delete object |
| PATCH | `/storage/v1/b/{bucket}/o/{object:path}` | Update object metadata |
| POST | `/storage/v1/b/{bucket}/o/{src_obj}/copyTo/b/{dst_bucket}/o/{dst_obj:path}` | Copy object |
| POST | `/storage/v1/b/{dst_bucket}/o/{dst_obj}/compose` | Compose object |
| POST | `/upload/storage/v1/b/{bucket}/o` | Upload (uploadType=media / multipart / resumable init) |
| PUT | `/upload/storage/v1/b/{bucket}/o` | Resumable upload chunk (session ID in `upload_id` query param) |

Path parameters with `{...:path}` use FastAPI's path-converter so slashes inside object names are captured. `google-cloud-storage` URL-encodes slashes when building requests, so the server decodes once on receipt.

Client detection of the emulator is **entirely client-side** — `STORAGE_EMULATOR_HOST` tells the client to target us. We do not enforce the presence of that env var.

## 4. Upload mechanics

All three upload types are required because `google-cloud-storage` selects between them based on file size and caller configuration; the emulator doesn't get to pick.

### 4.1 Simple upload (`uploadType=media`)

- Single `POST /upload/storage/v1/b/{bucket}/o?uploadType=media&name=<obj>` with `Content-Type` of the object and body = raw bytes.
- Server computes md5 / crc32c, assigns a generation, writes bytes + sidecar, publishes `gcs.object.finalize`, responds with full object metadata.

### 4.2 Multipart upload (`uploadType=multipart`)

- Single `POST /upload/storage/v1/b/{bucket}/o?uploadType=multipart` with body as `multipart/related`:
  - Part 1: `application/json` — object metadata (name, contentType, custom `metadata` dict, etc.).
  - Part 2: raw bytes.
- Server parses both parts, applies metadata from part 1, stores bytes from part 2, otherwise same as simple.

### 4.3 Resumable upload (`uploadType=resumable`)

The client library defaults to resumable for files over ~5 MiB, so this must work:

1. **Initiation:** client `POST /upload/storage/v1/b/{bucket}/o?uploadType=resumable&name=<obj>` with metadata JSON in body (or empty). Server allocates an opaque session ID and returns `201` with header `Location: http://<host>/upload/storage/v1/b/{bucket}/o?upload_id=<session-id>`.
2. **Session state:** server creates `/data/gcs/<bucket>/.uploads/<session-id>` containing:
   - `buffer.bin` — accumulated bytes so far
   - `session.json` — initial metadata, total size (if known), creation time, last-chunk timestamp
3. **Chunk upload:** client `PUT` to the session URL with `Content-Range: bytes N-M/total` (or `bytes N-M/*` if total is not yet known). Server appends bytes to buffer, updates last-chunk timestamp. Responds `308 Resume Incomplete` with `Range: bytes=0-M` header while more remains, or `200 OK` with full object metadata when the final chunk lands.
4. **Commit:** on final chunk, server moves `buffer.bin` to the object's final path, writes the sidecar, deletes the session dir, publishes `gcs.object.finalize`.
5. **Status query:** `PUT` with empty body and `Content-Range: bytes */*` returns the current `Range` header without appending — used by clients to resume after interruption.
6. **GC:** sessions older than 7 days are deleted on service start (matches real GCS's 7-day resumable-upload lifetime).

In in-memory mode, sessions live in a `dict[str, SessionState]` with the same lifecycle rules (minus the disk writes).

## 5. Storage layout

### 5.1 On-disk structure (`PERSIST=1`)

```
/data/gcs/
  <bucket>/
    <bucket>.meta.json              # bucket metadata
    objects/
      logs/
        2026/
          04/
            app.log                 # raw bytes
            app.log.meta.json       # per-object metadata sidecar
    .uploads/
      <session-id>/
        buffer.bin
        session.json
```

**Bucket-metadata filename** is `<bucket>.meta.json` rather than `.bucket.meta.json` so browsing `/data/gcs/<bucket>/` shows one obvious file describing the bucket and the `objects/` + `.uploads/` subdirectories.

**Collision rule** (the `foo` vs `foo/bar` filesystem edge case): if a `PutObject` would require creating a directory at a path currently occupied by an object file (or vice versa), the emulator returns `409 Conflict` with reason `"conflict"` and message `"object name collides with existing directory prefix"`. This diverges from real GCS (which allows the coexistence); we document it as a known emulator limitation. This matches fake-gcs-server's resolution of the same problem.

### 5.2 In-memory structure (default)

```python
class GcsState:
    buckets: dict[str, BucketMeta]
    objects: dict[tuple[bucket_name, object_name], ObjectRecord]
    uploads: dict[session_id, SessionState]
    generation_counter: dict[bucket_name, int]  # monotonic, atomic
```

Both backends implement the same `GcsStorage` Protocol; the service code is storage-agnostic.

### 5.3 Sidecar schema

`<object>.meta.json`:

```json
{
  "name": "logs/2026/04/app.log",
  "bucket": "my-bucket",
  "generation": 17,
  "metageneration": 1,
  "size": 1234,
  "contentType": "text/plain",
  "contentEncoding": "",
  "contentLanguage": "",
  "contentDisposition": "",
  "cacheControl": "",
  "md5Hash": "...",
  "crc32c": "...",
  "etag": "\"...\"",
  "timeCreated": "2026-04-24T10:30:00.000Z",
  "updated": "2026-04-24T10:30:00.000Z",
  "metadata": {"user-key": "user-value"}
}
```

## 6. Metadata, generations, and preconditions

### 6.1 Generation counter

Each bucket has a monotonically increasing `generation` counter. On every object create/overwrite, the counter is incremented and the new value stored on the object. `metageneration` resets to `1` on each object create/overwrite and increments by 1 on each metadata-only update (`PATCH`).

Concurrency: per-bucket `asyncio.Lock` around mutating operations ensures the counter is atomic and sidecars are consistent. Reads take no lock (GCS reads are eventually consistent anyway).

### 6.2 Precondition evaluation

Evaluated before any mutation, in this order:

1. `ifGenerationMatch=<g>` — must equal current object generation; else 412.
2. `ifGenerationNotMatch=<g>` — must NOT equal current object generation; else 304 (on GET) or 412 (on mutate).
3. `ifMetagenerationMatch=<mg>` — must equal; else 412.
4. `ifMetagenerationNotMatch=<mg>` — must NOT equal; else 304 or 412.

Special case: `ifGenerationMatch=0` means "only create if the object does not exist" — 412 if the object exists. `google-cloud-storage` uses this for "upload only if new."

412 responses carry body:
```json
{
  "error": {
    "code": 412,
    "message": "Precondition Failed",
    "errors": [{"domain": "global", "reason": "conditionNotMet", "message": "..."}],
    "status": "FAILED_PRECONDITION"
  }
}
```

## 7. State-hub event schema

The GCS service publishes events to the core's `StateHub` on every mutation. This is the forever contract that the Pub/Sub service will consume when it lands.

| Topic | When | Payload |
|---|---|---|
| `gcs.object.finalize` | Object created or overwritten (after generation is assigned) | See payload schema below |
| `gcs.object.metadata_update` | Only metadata changed (PATCH) | Same payload schema |
| `gcs.object.delete` | Object deleted | Same payload schema (populated with the deleted object's final state) |

Payload schema (Python `dict[str, Any]`, serializable to the real GCS object-change notification JSON shape):

```python
{
    "bucket": str,
    "name": str,
    "generation": int,
    "metageneration": int,
    "size": int,
    "contentType": str,
    "md5Hash": str,
    "crc32c": str,
    "timeCreated": str,   # RFC3339
    "updated": str,       # RFC3339
    "metadata": dict[str, str],
}
```

Fields match those the real GCS → Pub/Sub notification payload carries, so the Pub/Sub service can forward without translation.

Event publishing happens **after** the mutation is durable (sidecar written for disk mode, dict updated for in-memory mode), not before. If the handler chain raises, the mutation is still committed — the state hub already swallows handler exceptions.

## 8. HTTP error mapping

All error responses use the shared `rest_error_body()` helper from `gcp_local.core.errors`, which produces the GCS-compatible envelope (code, message, errors array with reason, status).

| Scenario | HTTP | reason | Notes |
|---|---|---|---|
| Bucket not found | 404 | `notFound` | |
| Object not found | 404 | `notFound` | |
| Bucket already exists | 409 | `conflict` | On create |
| Object collides with dir prefix | 409 | `conflict` | The `foo` + `foo/bar` case (documented quirk) |
| Precondition failed | 412 | `conditionNotMet` | |
| Malformed request | 400 | `invalid` | Bad body, bad params |
| Range not satisfiable | 416 | `invalid` | Range outside [0, size) |
| Upload session not found | 404 | `notFound` | Expired or unknown `upload_id` |
| Upload range mismatch | 400 | `invalid` | `Content-Range` inconsistent with session state |
| Compose source not found | 404 | `notFound` | |

## 9. Testing

### 9.1 Unit tests

Per-concern test modules:

- `test_gcs_storage_memory.py` / `test_gcs_storage_disk.py` — backend correctness (symmetric test suite parameterized over both backends).
- `test_gcs_generations.py` — generation + metageneration counters, atomic increments under concurrent access.
- `test_gcs_preconditions.py` — each precondition type, including `ifGenerationMatch=0` semantics.
- `test_gcs_uploads.py` — simple, multipart, resumable lifecycle (init, chunks, status query, commit, GC).
- `test_gcs_events.py` — state-hub event emission with payload schema verification.
- `test_gcs_errors.py` — each HTTP error shape.

### 9.2 Integration tests

Real `google-cloud-storage` Python client driving the emulator. Single file `test_gcs_integration.py` covering:

- `client.create_bucket("name")` → bucket visible via `client.list_buckets()` → `client.get_bucket("name")`
- `bucket.blob("obj").upload_from_string(b"hello")` (simple) → `blob.download_as_bytes() == b"hello"`
- `blob.upload_from_file(<10MB file>)` (triggers resumable) → download and byte-match
- `blob.upload_from_string("x", if_generation_match=0)` creating new → succeeds; same call on existing → `PreconditionFailed`
- `blob.reload()` after server-side change → reflects updated metageneration
- `blob.patch()` with custom metadata → `metageneration` increments by 1, `generation` stays same
- `bucket.list_blobs(prefix="logs/", page_size=3)` → paginates correctly
- `bucket.copy_blob(src_blob, dst_bucket, dst_name)` → destination exists with correct bytes
- `bucket.combine(src_blobs, dst_name)` (compose) → concatenated bytes
- `blob.download_as_bytes(start=100, end=200)` (ranged) → 100 bytes returned
- `blob.delete()` → subsequent `blob.reload()` → `NotFound`

Plus one test that subscribes a handler to the `StateHub` at start and asserts `gcs.object.finalize` and `gcs.object.delete` fire with the expected payload.

### 9.3 Dummy removal

Integration tests from the core (`tests/integration/test_core_end_to_end.py`) that reference the `dummy` service are updated to use `gcs` instead (or deleted if redundant with the GCS integration tests). The `src/gcp_local/services/_dummy/` package is removed and the `[project.entry-points."gcp_local.services"]` table loses the `dummy` entry and gains `gcs`.

## 10. Dependencies added

- None beyond what the core already has. FastAPI handles REST, `hashlib` handles md5, `google-crc32c` is the standard library for crc32c (pure-Python fallback acceptable).

New dependency in `pyproject.toml`:
- `google-crc32c>=1.5` — runtime

## 11. Open items

- Whether the server computes md5/crc32c from received bytes or trusts client-provided values in metadata when present. **Default: always compute from bytes.** Matches real GCS (which ignores client-supplied hashes in favor of server-computed ones). Client library sends its computed md5/crc32c in upload metadata and can verify against the response, but the authoritative hash is ours.
- Exact behavior when a client sends `If-None-Match: *` on a download (real GCS returns 304 if object exists). **Default: support it — returns 304.**
- What to return on `DELETE` of a nonexistent object with no preconditions. **Default: 404 / `notFound`.** Some clients also accept 200 for idempotency but real GCS returns 404.

## 12. Non-goals recap

This spec does not describe: versioning, signed URLs, IAM, CORS, HMAC, KMS, lifecycle rules, retention, XML API, notification config API, multi-region / storage-class semantics, requester-pays. All of these are deferred beyond v1.
