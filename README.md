<p align="center">
  <img src="docs/assets/icon.png" alt="gcp-local" width="160" />
</p>

# gcp-local

A local emulator for Google Cloud services — the GCP counterpart to LocalStack.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
<!-- TODO: add CI badge once the repo is public and Actions runs against master -->

`gcp-local` lets you point the official `google-cloud-*` Python client libraries at `localhost` and run integration tests, prototypes, and local developer workflows against a real-shaped emulator. No real GCP credentials, no real billing, no flaky network.

## Status

Alpha. Five services are implemented today; v1 is feature-complete. See [ROADMAP.md](ROADMAP.md) for per-service follow-ups and post-v1 plans.

## Services at a glance

| Service | Status | Default port | Wire | Usage | Architecture |
|---|---|---|---|---|---|
| BigQuery | Alpha | 9050 | REST | [usage](docs/services/bigquery.md) | [internals](docs/architecture/bigquery.md) |
| GCS | Alpha | 4443 | REST | [usage](docs/services/gcs.md) | [internals](docs/architecture/gcs.md) |
| Secret Manager | Alpha | 8086 | gRPC | [usage](docs/services/secret-manager.md) | [internals](docs/architecture/secret-manager.md) |
| Pub/Sub | Alpha | 8085 | gRPC | [usage](docs/services/pubsub.md) | [internals](docs/architecture/pubsub.md) |
| Firestore | Alpha | 8080 | gRPC | [usage](docs/services/firestore.md) | [internals](docs/architecture/firestore.md) |

Status vocabulary: **Stable** = feature-complete for v1, **Alpha** = implemented and in use but may shift, **Planned** = committed to v1 but not started, **Future** = post-v1.

## Quickstart

### Run from source

```bash
git clone https://github.com/aGallea/gcp-local.git
cd gcp-local
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m gcp_local
```

Health check:

```bash
curl http://localhost:4510/_emulator/health
```

### Run via Docker

Pre-built images are published to GitHub Container Registry on every push to `master` and on every `v*` tag:

```bash
docker run --rm -p 4510:4510 -p 4443:4443 -p 8080:8080 -p 8086:8086 -p 9050:9050 ghcr.io/agallea/gcp-local:latest
curl http://localhost:4510/_emulator/health
```

Available tags: `latest` (master tip), `master-<short-sha>` (specific master commit), `vX.Y.Z` / `vX.Y` (release tags). Multi-arch: `linux/amd64`, `linux/arm64`.

To build the image locally instead:

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
docker run --rm -p 4510:4510 -p 4443:4443 -p 8080:8080 -p 8086:8086 -p 9050:9050 gcp-local:dev
curl http://localhost:4510/_emulator/health
```

For docker-compose, Kubernetes, Rancher Desktop, persistence (`PERSIST=1`), and selecting a subset of services with `SERVICES=`, see [`docs/deployment.md`](docs/deployment.md).

### Browser UI

A bundled web UI ships with the emulator. Open:

```
http://localhost:4510/ui/
```

What's in this release: a full GCS browser — buckets, blobs, folder navigation, create/delete folders, drag-and-drop upload, inline preview (text / JSON / image), and download — plus a BigQuery browser with project / dataset / table navigation, schema view, paged row preview, and an ad-hoc SQL query console. The remaining services (Secret Manager, Pub/Sub, Firestore) appear in the sidebar greyed out as "coming soon"; per-service follow-up specs will land each in turn.

The UI is local-only and performs no authentication. **Never expose port 4510 on a non-loopback interface** — anyone who can reach it can read and mutate every service's state.

## Connect a client

### BigQuery

```python
import os
from google.auth import credentials as ga_credentials
from google.cloud import bigquery
from google.cloud.bigquery import DatasetReference, SchemaField, TableReference

os.environ["BIGQUERY_EMULATOR_HOST"] = "localhost:9050"
client = bigquery.Client(
    project="my-project",
    credentials=ga_credentials.AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:9050"},
)

ds_ref = DatasetReference("my-project", "demo")
client.create_dataset(bigquery.Dataset(ds_ref))

schema = [SchemaField("id", "INT64", mode="REQUIRED"), SchemaField("name", "STRING")]
table_ref = TableReference(ds_ref, "greetings")
client.create_table(bigquery.Table(table_ref, schema=schema))
client.insert_rows_json(table_ref, [{"id": 1, "name": "hello"}])

rows = list(client.query("SELECT * FROM `my-project.demo.greetings`").result())
print(rows)
```

### GCS

```python
import os
from google.auth import credentials as ga_credentials
from google.cloud import storage

os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:4443"
client = storage.Client(
    project="my-project",
    credentials=ga_credentials.AnonymousCredentials(),
)
bucket = client.create_bucket("my-bucket")
bucket.blob("hello.txt").upload_from_string("hi from gcp-local")
print(bucket.blob("hello.txt").download_as_text())
```

### Secret Manager

```python
from google.api_core import client_options as co
from google.auth import credentials as ga_credentials
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient(
    credentials=ga_credentials.AnonymousCredentials(),
    client_options=co.ClientOptions(api_endpoint="localhost:8086"),
    transport="grpc",
)

parent = "projects/my-project"
secret = client.create_secret(
    parent=parent,
    secret_id="my-secret",
    secret={"replication": {"automatic": {}}},
)
client.add_secret_version(parent=secret.name, payload={"data": b"shh"})
print(
    client.access_secret_version(name=f"{secret.name}/versions/latest").payload.data
)
```

### Pub/Sub

```python
import os
from google.cloud import pubsub_v1

os.environ["PUBSUB_EMULATOR_HOST"] = "localhost:8085"

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path("my-project", "my-topic")
publisher.create_topic(request={"name": topic_path})

subscriber = pubsub_v1.SubscriberClient()
sub_path = subscriber.subscription_path("my-project", "my-sub")
subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})

publisher.publish(topic_path, b"hello from gcp-local").result()

response = subscriber.pull(request={"subscription": sub_path, "max_messages": 1})
for received in response.received_messages:
    print(received.message.data)
    subscriber.acknowledge(
        request={"subscription": sub_path, "ack_ids": [received.ack_id]}
    )
```

### Firestore

```python
import os
from google.cloud import firestore

os.environ["FIRESTORE_EMULATOR_HOST"] = "localhost:8080"

db = firestore.Client(project="my-project")
db.collection("users").document("alice").set({"name": "Alice", "score": 0})
db.collection("users").document("alice").update({"score": firestore.Increment(1)})

snap = db.collection("users").document("alice").get()
print(snap.to_dict())  # {'name': 'Alice', 'score': 1}

for doc in db.collection("users").where(
    filter=firestore.FieldFilter("score", ">", 0)
).stream():
    print(doc.id, doc.to_dict())
```

## Documentation map

- **Use a service** — [`docs/services/`](docs/services/) (one file per service: BigQuery, GCS, Secret Manager, Pub/Sub, Firestore).
- **End-to-end example** — [`examples/order-pipeline/`](examples/order-pipeline/) (uses all five services together; runs as the CI e2e test).
- **Run / deploy** — [`docs/deployment.md`](docs/deployment.md).
- **Architecture & internals** — [`docs/architecture/overview.md`](docs/architecture/overview.md) and the per-service files alongside it.
- **Roadmap** — [`ROADMAP.md`](ROADMAP.md).
- **Contribute** — [`CONTRIBUTING.md`](CONTRIBUTING.md). For a brand-new service: [`docs/development/adding-a-service.md`](docs/development/adding-a-service.md).
- **Changelog** — [`CHANGELOG.md`](CHANGELOG.md).

## License

Apache 2.0. See [`LICENSE`](LICENSE).

## Reporting issues

Bugs and feature requests: [GitHub issues](https://github.com/aGallea/gcp-local/issues) (templates available).

Security: see [`SECURITY.md`](SECURITY.md). The TL;DR is: GitHub Security Advisories preferred, `asafgallea@gmail.com` as backup.
