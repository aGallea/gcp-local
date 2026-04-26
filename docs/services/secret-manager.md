# Secret Manager emulator

gcp-local's Secret Manager service emulates the Google Cloud Secret Manager gRPC API. The official `google-cloud-secret-manager` Python client works against it with no code changes beyond pointing at the emulator host.

Default port: **8086**. The wire protocol is **gRPC** — unlike BigQuery and GCS, Secret Manager has no `*_EMULATOR_HOST` environment variable. Clients connect by passing `client_options.api_endpoint` directly to the constructor (see [Connecting](#connecting) below).

---

## What's emulated

**Secret lifecycle**
- `CreateSecret` — creates an empty secret; labels and annotations are accepted and stored
- `GetSecret` — returns the secret record including labels, annotations, and creation timestamp
- `ListSecrets` — lists all secrets under a project, sorted by secret ID; supports `page_size` + `page_token` cursor pagination (page size capped at 250)
- `UpdateSecret` — applies `update_mask`-controlled field patches (labels and annotations); fields outside the mask are ignored silently
- `DeleteSecret` — deletes the secret and all its versions; `etag` is accepted if provided

**Version lifecycle**
- `AddSecretVersion` — appends a new version with the supplied payload bytes; new versions start in `ENABLED` state; server computes and stores `data_crc32c` for round-trip integrity
- `GetSecretVersion` — returns version metadata (state, timestamps); accepts `"latest"` as the version specifier
- `ListSecretVersions` — lists all versions for a secret including `DISABLED` and `DESTROYED` ones; supports pagination
- `AccessSecretVersion` — returns the payload bytes for an `ENABLED` version; accepts `"latest"` to resolve the highest-ID enabled version; rejects `DISABLED` or `DESTROYED` versions with `FAILED_PRECONDITION`
- `EnableSecretVersion` / `DisableSecretVersion` / `DestroySecretVersion` — state transitions per the table in [Version states](#version-states)

**Resource-name validation**
- Secret names follow the form `projects/<project>/secrets/<secret_id>`
- Version names follow the form `projects/<project>/secrets/<secret_id>/versions/<version_id>`, where `<version_id>` is a positive integer or `"latest"`
- `secret_id` must match `[A-Za-z0-9_-]{1,255}`; invalid IDs are rejected with `INVALID_ARGUMENT`

**Project namespacing**
- Each `(project, secret_id)` pair is an independent resource; two projects can hold secrets with the same ID without colliding

**Storage backends**
- In-memory (default) — all data is lost when the emulator stops
- Disk-backed (`PERSIST=1`) — state serialized to `/data/secret_manager/secret_manager.json`; survives container restarts

---

## What's not emulated (v1)

- **IAM** — `GetIamPolicy`, `SetIamPolicy`, and `TestIamPermissions` return `UNIMPLEMENTED`; no access control is enforced on any endpoint
- **Customer-managed encryption keys (CMEK)** — `customer_managed_encryption` in `CreateSecret` is accepted and stored in labels; no encryption is applied; payloads are stored as-is in cleartext
- **Replication policy enforcement** — `replication` (`automatic` or `user_managed`) is accepted in `CreateSecret` but not acted on; all secrets behave as if `automatic` replication is in effect
- **Rotation schedules** — `rotation` and `topics` fields in `CreateSecret` / `UpdateSecret` are accepted and silently ignored
- **`expire_time` and TTL on versions** — not enforced; no version is expired automatically
- **Audit logging** — no Cloud Audit Logs equivalent; all accesses are accepted regardless of IAM
- **REST transport** — the official Python client defaults to gRPC; the REST (`_mtls_endpoint` / `rest` transport) surface is not wired up in v1
- **Real cryptographic guarantees** — payloads are not encrypted at rest

---

## Version states

| From \ To | ENABLED | DISABLED | DESTROYED |
|---|---|---|---|
| **ENABLED** | no-op | allowed | allowed |
| **DISABLED** | allowed | no-op | allowed |
| **DESTROYED** | `FAILED_PRECONDITION` | `FAILED_PRECONDITION` | no-op |

`DestroySecretVersion` additionally zeroes the stored payload and sets `destroy_time`. The version record is retained in `ListSecretVersions` results (with a cleared payload field) so callers can see the version's state history.

`"latest"` resolves to the **highest-ID version in `ENABLED` state**. Disabled and destroyed versions are skipped. If no enabled version exists (e.g. all have been disabled or destroyed), `AccessSecretVersion` and `GetSecretVersion("latest")` return `FAILED_PRECONDITION`.

---

## Connecting

Secret Manager has no `SECRET_MANAGER_EMULATOR_HOST` environment variable (unlike the BigQuery or GCS clients). Use `client_options.api_endpoint` with `transport="grpc"`:

```python
from google.api_core import client_options as co
from google.auth import credentials as ga_credentials
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient(
    credentials=ga_credentials.AnonymousCredentials(),
    client_options=co.ClientOptions(
        api_endpoint="localhost:8086",
    ),
    transport="grpc",
)
```

**`AnonymousCredentials` is required.** The emulator performs no authentication. Without it, the client attempts Application Default Credentials, which may fail or send real tokens to the emulator (which ignores them, but the client may still reject the plain-text endpoint).

**`transport="grpc"` is required.** The Secret Manager client defaults to `grpc_asyncio` when running in an async event loop and `grpc` otherwise. Passing it explicitly ensures the client opens an insecure channel when `api_endpoint` does not have TLS.

**No `http://` prefix.** Unlike the GCS `STORAGE_EMULATOR_HOST`, the `api_endpoint` for gRPC services is a bare `host:port` string — no scheme.

### Port override

Override the default port with the `SECRET_MANAGER_EMULATOR_PORT` environment variable before starting the emulator:

```bash
SECRET_MANAGER_EMULATOR_PORT=9100 python -m gcp_local
```

Then pass `api_endpoint="localhost:9100"` in the client constructor.

---

## Quickstart

```python
from google.api_core import client_options as co
from google.auth import credentials as ga_credentials
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient(
    credentials=ga_credentials.AnonymousCredentials(),
    client_options=co.ClientOptions(api_endpoint="localhost:8086"),
    transport="grpc",
)

PROJECT = "my-project"
parent = f"projects/{PROJECT}"

# 1. Create a secret
secret = client.create_secret(
    request={
        "parent": parent,
        "secret_id": "db-password",
        "secret": {"replication": {"automatic": {}}},
    }
)
print(secret.name)
# projects/my-project/secrets/db-password

# 2. Add a version
version = client.add_secret_version(
    request={
        "parent": secret.name,
        "payload": {"data": b"s3cr3t-v4lue"},
    }
)
print(version.name)
# projects/my-project/secrets/db-password/versions/1

# 3. Access the latest version
response = client.access_secret_version(
    request={"name": f"{secret.name}/versions/latest"}
)
print(response.payload.data)
# b's3cr3t-v4lue'

# 4. Access by explicit version number
response_v1 = client.access_secret_version(
    request={"name": f"{secret.name}/versions/1"}
)
assert response_v1.payload.data == b"s3cr3t-v4lue"

# 5. Delete the secret (and all versions)
client.delete_secret(request={"name": secret.name})
```

---

## Examples

The examples below assume `client` is already constructed per the [Connecting](#connecting) snippet, and `PROJECT = "my-project"`.

### Create a secret

```python
secret = client.create_secret(
    request={
        "parent": f"projects/{PROJECT}",
        "secret_id": "api-key",
        "secret": {
            "replication": {"automatic": {}},
            "labels": {"env": "dev", "team": "backend"},
        },
    }
)
print(secret.name)
# projects/my-project/secrets/api-key
print(dict(secret.labels))
# {'env': 'dev', 'team': 'backend'}
```

### Add a version

```python
version = client.add_secret_version(
    request={
        "parent": "projects/my-project/secrets/api-key",
        "payload": {"data": b"my-secret-payload"},
    }
)
print(version.name)
# projects/my-project/secrets/api-key/versions/1
print(version.state)
# State.ENABLED
```

The server computes `data_crc32c` and stores it. You can assert the value for extra safety:

```python
import google_crc32c

payload = b"my-secret-payload"
version = client.add_secret_version(
    request={
        "parent": "projects/my-project/secrets/api-key",
        "payload": {
            "data": payload,
            "data_crc32c": google_crc32c.value(payload),
        },
    }
)
```

### Access a version by `latest` and by number

```python
# Resolve "latest" — returns the highest-ID enabled version
response = client.access_secret_version(
    request={"name": "projects/my-project/secrets/api-key/versions/latest"}
)
print(response.payload.data)
# b'my-secret-payload'

# Access by explicit version number
response_v1 = client.access_secret_version(
    request={"name": "projects/my-project/secrets/api-key/versions/1"}
)
assert response_v1.payload.data == b"my-secret-payload"
```

### List versions

```python
for version in client.list_secret_versions(
    request={"parent": "projects/my-project/secrets/api-key"}
):
    print(version.name, version.state)
# projects/my-project/secrets/api-key/versions/1 State.ENABLED
```

`ListSecretVersions` includes `DISABLED` and `DESTROYED` versions, matching real Secret Manager behavior. Filter them in your own code if you only want active versions.

### Disable, re-enable, and destroy a version

```python
from google.cloud.secretmanager_v1.types import SecretVersion

version_name = "projects/my-project/secrets/api-key/versions/1"

# Disable
disabled = client.disable_secret_version(request={"name": version_name})
print(disabled.state)
# State.DISABLED

# Accessing a disabled version raises FailedPrecondition
from google.api_core import exceptions as gce
try:
    client.access_secret_version(request={"name": version_name})
except gce.FailedPrecondition as exc:
    print("cannot access disabled version:", exc)

# Re-enable
client.enable_secret_version(request={"name": version_name})

# Destroy — payload is zeroed; version record is retained
client.destroy_secret_version(request={"name": version_name})
```

### Update secret labels

```python
from google.protobuf import field_mask_pb2

secret_name = "projects/my-project/secrets/api-key"
updated = client.update_secret(
    request={
        "secret": {
            "name": secret_name,
            "labels": {"env": "prod"},
        },
        "update_mask": field_mask_pb2.FieldMask(paths=["labels"]),
    }
)
print(dict(updated.labels))
# {'env': 'prod'}
```

Only fields listed in `update_mask` are applied. Fields absent from the mask are left untouched regardless of what is in the request body.

### Delete a secret

```python
client.delete_secret(
    request={"name": "projects/my-project/secrets/api-key"}
)

# Subsequent get raises NotFound
try:
    client.get_secret(request={"name": "projects/my-project/secrets/api-key"})
except gce.NotFound:
    print("secret is gone")
```

Deleting a secret removes it and all its versions in one call. There is no soft-delete or recycle bin.

---

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `SECRET_MANAGER_EMULATOR_PORT` | `8086` | Port the Secret Manager gRPC server listens on |
| `PERSIST` | `0` | Set to `1` to use disk-backed storage instead of in-memory |

### Disk layout (PERSIST=1)

When `PERSIST=1`, all secrets and versions are serialized to a single JSON file:

```
/data/secret_manager/
  secret_manager.json    # full catalog: all secrets + all versions
```

The file is rewritten on every mutation (write-through). Secrets are small, so this is fast in practice; it avoids partial-update consistency bugs that a journal-based approach would introduce.

Payload bytes are stored as base64 inside the JSON file. There is no encryption at rest.

---

## Reset semantics

`POST /_emulator/reset?service=secret_manager`

Drops all secrets and all versions. With `PERSIST=1`, the on-disk catalog file is deleted. Useful between test cases.

```bash
curl -X POST http://localhost:4510/_emulator/reset?service=secret_manager
```

Note: the reset endpoint is served by the admin API on port **4510**, not on the Secret Manager gRPC port (8086). Sending it to the gRPC port will fail.

---

## Limits & quirks

**No authentication.** Every caller can read and write every secret in every project. `AnonymousCredentials` is the only supported credential type. Any other credential object may cause the client to reject the plain-text (non-TLS) connection before the request even reaches the emulator.

**Payloads stored in cleartext.** CMEK and envelope encryption are not emulated. The JSON catalog file written by `PERSIST=1` contains base64-encoded raw bytes. Do not store real secrets in the emulator.

**No `*_EMULATOR_HOST` shortcut.** Unlike BigQuery (`BIGQUERY_EMULATOR_HOST`) and GCS (`STORAGE_EMULATOR_HOST`), Secret Manager has no client-library environment variable that redirects to a local host. You must pass `client_options` and `transport="grpc"` explicitly every time you construct a client.

**Version IDs are monotonic and never reused.** After `DestroySecretVersion`, the version ID is gone forever. If you add a new version, it gets the next integer in the sequence, not the destroyed slot. This matches real Secret Manager behavior.

**`"latest"` skips non-enabled versions.** If all versions of a secret are disabled or destroyed, `AccessSecretVersion("latest")` returns `FAILED_PRECONDITION`, not `NOT_FOUND`. Callers should handle both `NOT_FOUND` (secret does not exist) and `FAILED_PRECONDITION` (secret exists but has no accessible version).

**Pagination uses a cursor over `secret_id` strings.** The `page_token` returned by `ListSecrets` is an opaque base64-encoded `secret_id`. If a secret is deleted between two `ListSecrets` pages, the cursor skips cleanly to the next result. Page size is capped at 250 regardless of what is passed in `page_size`.

**Async event loop.** `google-cloud-secret-manager` with `transport="grpc"` (synchronous gRPC) blocks the calling thread. If you use the emulator in-process inside an async pytest test, dispatch client calls to a thread to avoid blocking the event loop:

```python
import asyncio

async def _run(fn):
    return await asyncio.get_running_loop().run_in_executor(None, fn)

await _run(lambda: client.access_secret_version(
    request={"name": "projects/my-project/secrets/api-key/versions/latest"}
))
```

**`etag` is accepted but not enforced.** `UpdateSecret` and `DeleteSecret` accept an `etag` field for optimistic concurrency, but the emulator does not validate it — any value (including an empty string) passes. The emulator returns a computed `etag` on reads so client code that echoes it back does not break.

**Secret ID character set.** `secret_id` must match `[A-Za-z0-9_-]{1,255}`. Attempting to create a secret with a name containing dots, slashes, or spaces returns `INVALID_ARGUMENT`. Real Secret Manager enforces the same rule.

**IAM stubs return `UNIMPLEMENTED`.** Calls to `GetIamPolicy`, `SetIamPolicy`, or `TestIamPermissions` return gRPC status `UNIMPLEMENTED`. Client code that calls these methods (e.g. to check permissions before accessing a secret) will raise `google.api_core.exceptions.NotImplemented`.
