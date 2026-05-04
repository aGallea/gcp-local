# Cloud Storage emulator

gcp-local's GCS service emulates the Google Cloud Storage JSON API. The official `google-cloud-storage` Python client works against it with no code changes beyond pointing at the emulator host.

Default port: **4443**.

---

## What's emulated

**Buckets**
- `POST /storage/v1/b` — create bucket (location, storageClass accepted and stored)
- `GET /storage/v1/b` — list all buckets
- `GET /storage/v1/b/{bucket}` — get bucket metadata
- `DELETE /storage/v1/b/{bucket}` — delete bucket (cascades to all objects)

**Objects — reads**
- `GET /storage/v1/b/{bucket}/o` — list objects with `prefix`, `delimiter`, `maxResults`, and `pageToken` cursor pagination
- `GET /storage/v1/b/{bucket}/o/{name}` — get object metadata (`alt=json`, default) or raw bytes (`alt=media`)
- `GET /download/storage/v1/b/{bucket}/o/{name}` — download endpoint used by the client library; supports `Range` header for partial content (HTTP 206)
- `DELETE /storage/v1/b/{bucket}/o/{name}` — delete object

**Objects — writes**
- `POST /upload/storage/v1/b/{bucket}/o?uploadType=media` — simple (single-request) upload
- `POST /upload/storage/v1/b/{bucket}/o?uploadType=multipart` — multipart upload (JSON metadata part + binary part)
- `POST /upload/storage/v1/b/{bucket}/o?uploadType=resumable` — initiate resumable upload session
- `PUT /upload/storage/v1/b/{bucket}/o?upload_id=…` — upload chunk or complete resumable session; status query (`Content-Range: bytes */*`) returns HTTP 308 with `Range` header
- `PATCH /storage/v1/b/{bucket}/o/{name}` — update object metadata (contentType, contentEncoding, contentLanguage, contentDisposition, cacheControl, custom metadata)

**Copy and compose**
- `POST /storage/v1/b/{src}/o/{name}/copyTo/b/{dst}/o/{dst_name}` — copy object across buckets or within a bucket; metadata is carried over
- `POST /storage/v1/b/{bucket}/o/{name}/compose` — compose up to 32 source objects into one destination object

**Preconditions** on uploads, patch, and copy:
- `ifGenerationMatch` / `ifGenerationNotMatch`
- `ifMetagenerationMatch` / `ifMetagenerationNotMatch`

## What's not emulated (v1)

- IAM: `getIamPolicy`, `setIamPolicy`, `testIamPermissions` — any auth/IAM surface returns no-op or 404
- Notifications / Pub/Sub triggers — the emulator fires internal `StateHub` events (`gcs.object.finalize`, `gcs.object.delete`, `gcs.object.metadata_update`) for cross-service wiring, but there is no GCS-to-Pub/Sub notification configuration API
- Object versioning — generation numbers are assigned and honored in preconditions, but there is no versioning config; only the latest generation of each object name is retained
- Bucket-level retention policies, lifecycle rules, CORS, requester-pays, uniform bucket-level access
- Signed URLs and HMAC keys
- Bucket ACLs and object ACLs (separate from IAM)
- Rewrite API (`rewriteTo`) — use `copyTo` instead
- XML API (S3-compatible endpoint)
- gRPC Storage v2 (`google.storage.v2`)
- Customer-managed encryption keys (CMEK)
- Object holds (temporary and event-based)
- Storage Transfer Service and Batch operations

---

## Connecting

### Environment variable (simplest)

```python
import os
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:4443"
client = storage.Client(
    project="my-project",
    credentials=AnonymousCredentials(),
)
```

### Explicit `client_options` (more portable across client-library versions)

```python
import os
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:4443"
client = storage.Client(
    project="my-project",
    credentials=AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:4443"},
)
```

**`AnonymousCredentials` is required.** The emulator performs no authentication. Without it, the client attempts Application Default Credentials, which may fail or send real credentials to the emulator (which ignores them, but the client may still raise on an HTTP-not-HTTPS endpoint).

**`STORAGE_EMULATOR_HOST` must include the scheme.** The `google-cloud-storage` client reads this variable and uses it verbatim as the base URL; omitting `http://` causes connection failures.

---

## Quickstart

```python
import os
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:4443"
client = storage.Client(
    project="my-project",
    credentials=AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:4443"},
)

# 1. Create a bucket
bucket = client.create_bucket("my-bucket")

# 2. Upload an object
blob = bucket.blob("hello.txt")
blob.upload_from_string(b"hello world", content_type="text/plain")

# 3. Download it back
data = bucket.blob("hello.txt").download_as_bytes()
assert data == b"hello world"

# 4. List objects
for b in bucket.list_blobs(prefix="hello"):
    print(b.name, b.size)

# 5. Delete the object
bucket.blob("hello.txt").delete()

# 6. Delete the bucket
bucket.delete()
```

---

## Browser UI

A bundled web UI lets you inspect and manipulate GCS state without writing any code. Open:

```
http://localhost:4510/ui/
```

The UI is served by the admin port (4510), not the GCS wire port. What you can do today:

- List, create, and delete buckets.
- List blobs with prefix-folder navigation (breadcrumb segment links, `delimiter=/` semantics).
- Create folders. Folders are 0-byte placeholder objects whose name ends in `/`; they show up in `list_blobs` exactly the same as any other object.
- Delete folder placeholders.
- Upload (drag-and-drop or file picker). The default upload cap is 100 MB; raise it with `GCP_LOCAL_UI_MAX_UPLOAD_MB`.
- Download blobs.
- Inline preview for text, JSON, and image blobs (1 MB cap for text/JSON, 5 MB for images; oversized blobs surface a download link instead).
- Delete blobs.

The UI reads and writes the **same in-process state** as the GCS REST API on port 4443. An object you upload via `gsutil` shows up in the UI immediately, and vice versa. There is no auth; the emulator is local-only.

Under the hood the UI calls a separate, internal namespace at `/_emulator/ui-api/v1/...` — versioned and explicitly not part of the GCS wire contract. Client libraries (`google-cloud-storage`, `gsutil`, etc.) continue to talk to the public REST surface on port 4443.

---

## Resumable and multipart uploads

### Multipart upload

The client library uses multipart upload automatically for small objects when metadata is provided alongside the bytes. The emulator parses the `multipart/related` body, extracts the JSON metadata part (name, contentType, custom metadata) and the binary part, and creates the object atomically.

```python
blob = bucket.blob("notes.txt")
blob.metadata = {"author": "alice"}
blob.upload_from_string(b"some text", content_type="text/plain")
```

### Resumable upload

Objects larger than ~8 MiB are uploaded via the resumable protocol automatically by the client library. You can also force it:

```python
import io

data = b"x" * (10 * 1024 * 1024)  # 10 MiB
blob = bucket.blob("big.bin")
blob.upload_from_file(
    io.BytesIO(data),
    content_type="application/octet-stream",
    size=len(data),
)
```

The emulator:
1. Creates a session on `POST …?uploadType=resumable` and returns a `Location` header with `upload_id`.
2. Accepts sequential chunks on `PUT …?upload_id=…` with `Content-Range: bytes N-M/total` headers. Each incomplete chunk returns HTTP 308 with a `Range` header indicating received bytes.
3. Finalizes the object once the last chunk is received, computing MD5 and CRC32C checksums over the full payload.

**Status query.** Sending `Content-Range: bytes */*` returns HTTP 308 with the `Range` of bytes received so far (useful for resuming after a disconnection).

**Known gap.** The emulator enforces strict sequential ordering of chunks: each chunk's start byte must equal `bytes_received`. Out-of-order or overlapping chunks return HTTP 400. In-flight network interruption followed by a resume is supported via the status query, but the re-sent chunk must begin exactly at the acknowledged offset.

---

## Object metadata

Every object record carries the following metadata, all of which round-trip correctly through the client library:

| Field | Notes |
|---|---|
| `contentType` | Defaults to `application/octet-stream` if not provided |
| `contentEncoding` | Optional; stored verbatim |
| `contentLanguage` | Optional; stored verbatim |
| `contentDisposition` | Optional; stored verbatim |
| `cacheControl` | Optional; stored verbatim |
| `metadata` | Arbitrary `string → string` custom metadata map |
| `generation` | Monotonic integer assigned at object creation/overwrite |
| `metageneration` | Starts at `1`; incremented by each `PATCH` |
| `md5Hash` | Base64-encoded MD5 over the raw bytes |
| `crc32c` | Base64-encoded CRC32C over the raw bytes |
| `timeCreated` | RFC 3339 timestamp set at first creation; preserved on overwrite |
| `updated` | RFC 3339 timestamp updated on every write or patch |
| `etag` | Computed as `"<generation>/<metageneration>"` |
| `size` | Byte count |

### Patching metadata

Use `blob.patch()` or `blob.reload()` + attribute assignment:

```python
blob = bucket.blob("notes.txt")
blob.upload_from_string(b"hello")

# Update custom metadata and content type
blob.metadata = {"owner": "bob"}
blob.content_type = "text/plain"
blob.patch()

# Confirm the update
fresh = bucket.blob("notes.txt")
fresh.reload()
print(fresh.metadata)       # {"owner": "bob"}
print(fresh.metageneration) # 2
```

---

## Preconditions (conditional requests)

The emulator supports all four standard GCS precondition query parameters on upload and patch operations.

| Parameter | Behavior |
|---|---|
| `ifGenerationMatch=0` | Succeeds only if the object does **not** exist (create-only) |
| `ifGenerationMatch=N` | Succeeds only if the object's current generation equals `N` |
| `ifGenerationNotMatch=N` | Succeeds only if the object's current generation differs from `N` |
| `ifMetagenerationMatch=N` | Succeeds only if metageneration equals `N` |
| `ifMetagenerationNotMatch=N` | Succeeds only if metageneration differs from `N` |

A failed precondition returns HTTP 412. The client library raises `google.api_core.exceptions.PreconditionFailed`.

```python
from google.api_core import exceptions as gce

blob = bucket.blob("once.txt")
blob.upload_from_string(b"first write", if_generation_match=0)

# Second write with if_generation_match=0 raises PreconditionFailed
try:
    bucket.blob("once.txt").upload_from_string(b"second write", if_generation_match=0)
except gce.PreconditionFailed:
    print("object already exists")
```

Preconditions on resumable uploads apply at session-creation time. At finalization time, a bare `Preconditions()` (no conditions) is used, so only the conditions supplied when initiating the session are enforced.

---

## Object change events (StateHub)

The GCS service publishes internal events to the `StateHub` pub/sub bus on three operations:

| Event topic | Trigger |
|---|---|
| `gcs.object.finalize` | Object created or overwritten (simple, multipart, resumable, copy, compose) |
| `gcs.object.metadata_update` | Object metadata patched via `PATCH` |
| `gcs.object.delete` | Object deleted |

The event payload for all three topics is:

```json
{
  "bucket":         "my-bucket",
  "name":           "path/to/object",
  "generation":     1,
  "metageneration": 1,
  "size":           11,
  "contentType":    "text/plain",
  "md5Hash":        "…",
  "crc32c":         "…",
  "timeCreated":    "2025-01-01T00:00:00.000000Z",
  "updated":        "2025-01-01T00:00:00.000000Z",
  "metadata":       {}
}
```

These events are used for cross-service wiring within a single emulator process. To subscribe from another service or test code:

```python
from gcp_local.core.state_hub import StateHub
from gcp_local.services.gcs.events import EVENT_FINALIZE

hub: StateHub = ...  # obtained from the Context passed to your service

async def on_object_created(event: dict) -> None:
    print("new object:", event["bucket"], event["name"])

hub.subscribe(EVENT_FINALIZE, on_object_created)
```

**No GCS-to-Pub/Sub notification API is wired up.** If you need GCS object change notifications to trigger Pub/Sub messages, you would subscribe to the `StateHub` events from a future Pub/Sub service implementation. At present the events are available in-process only.

---

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `STORAGE_EMULATOR_HOST` | — | Consumed by `google-cloud-storage`; set to `http://localhost:4443` (include scheme) |
| `GCS_EMULATOR_PORT` | `4443` | Port the GCS service listens on |
| `PERSIST` | `0` | Set to `1` to use disk-backed storage instead of in-memory |

### Disk layout (PERSIST=1)

When `PERSIST=1`, objects are written under `$GCP_LOCAL_DATA_DIR/gcs/` (default: `/data/gcs/`). The layout is:

```
gcs/
  <bucket>/
    <bucket>.meta.json          # bucket metadata
    objects/
      <path/to/object>          # raw bytes
      <path/to/object>.meta.json  # object record (generation, checksums, etc.)
    .uploads/
      <session_id>/
        session.json            # resumable upload session state
        buffer.bin              # accumulated bytes for in-flight sessions
```

Stale upload sessions older than 7 days are garbage-collected automatically on startup.

---

## Reset semantics

`POST /_emulator/reset?service=gcs`

Drops all buckets, objects, and in-flight upload sessions; resets all generation counters. With `PERSIST=1`, disk contents are deleted. Useful between test cases.

```bash
curl -X POST http://localhost:4443/_emulator/reset?service=gcs
```

Note: the reset endpoint is served by the admin API, which defaults to port `4510`. If you are issuing the request directly to the GCS port rather than the admin port, check your setup. In the integration tests, `/_emulator/reset` is registered on the GCS app itself via the core admin router.

---

## Known gaps

These are intentional v1 limitations, not bugs.

**Auth / IAM.** No authentication is enforced. `AnonymousCredentials` must be used; all requests are accepted regardless of credential content.

**Object versioning.** Uploading an object with the same name overwrites the previous version. The previous generation is not retained and cannot be accessed by generation number. Preconditions based on generation numbers work against the live (only) generation.

**Resumable upload preconditions.** Preconditions supplied when initiating a resumable session are evaluated at initiation, not at finalization. If another writer overwrites the object between session initiation and the final chunk, the precondition will not catch it.

**No XML API.** Only the JSON REST API is implemented. `boto3` or any S3-compatible client will not work against this emulator.

**Rewrite API.** `POST …/rewriteTo/…` is not implemented. Use `copyTo` instead; it works for same-bucket renames and cross-bucket copies within the emulator.

**No GCS-to-Pub/Sub notification configuration.** `POST /storage/v1/b/{bucket}/notificationConfigs` is not implemented. Cross-service events are available only via the internal `StateHub`.

**Object ACLs and bucket ACLs.** The `acl` and `defaultObjectAcl` resources are not implemented.

**Signed URLs.** `generate_signed_url()` on a `Blob` object will attempt to call GCP signing APIs, which requires real credentials. Signed URLs cannot be generated against the emulator.

---

## Caveats / gotchas

**Async event loop blocking.** `google-cloud-storage` is synchronous (uses `requests` under the hood). If you run both the emulator and client code in the same async event loop (e.g. in an async pytest test), calling storage methods directly will block the loop and starve the in-process uvicorn server — the call hangs. Dispatch all client calls to a thread:

```python
import asyncio

async def _run(fn):
    return await asyncio.get_running_loop().run_in_executor(None, fn)

# Instead of: blob.upload_from_string(b"data")
await asyncio.to_thread(blob.upload_from_string, b"data")

# Or via executor:
await _run(lambda: blob.download_as_bytes())
```

See `tests/integration/test_gcs_integration.py` for the full pattern used in this project's integration tests.

**`STORAGE_EMULATOR_HOST` must include `http://`.** The variable is consumed as-is by the client library. Without the scheme, requests go to `https://` and fail with TLS errors.

**Bucket names.** The emulator accepts any non-empty string as a bucket name. The real GCS enforces DNS-compliant naming rules (lowercase, 3–63 characters, no consecutive dots, etc.). Tests using names like `my_bucket` or `TEST` will work locally but would fail against real GCS.

**Project IDs.** The emulator accepts any project string and does not enforce quotas or cross-project visibility rules. All buckets are globally visible regardless of which project ID the client uses.

**Compose limit.** Compose accepts at most 32 source objects, matching the real GCS limit. Requests with more than 32 sources return HTTP 400.
