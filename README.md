# gcp-local

A local emulator for Google Cloud Platform services — the GCP counterpart to LocalStack. Apache 2.0.

## Status

Alpha. The emulator currently provides working implementations of GCS, Secret Manager, and BigQuery. Pub/Sub and Firestore are planned for v1; Cloud Functions for v2.

The Python client libraries for all three services work against the emulator with no code changes beyond pointing at `localhost`.

## Quickstart

Install from source (PyPI release is not yet available):

```bash
git clone https://github.com/aGallea/gcp-local.git
cd gcp-local
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Start the emulator with all services:

```bash
python -m gcp_local
```

### Run via Docker

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
docker run --rm -p 4510:4510 -p 4443:4443 -p 8086:8086 -p 9050:9050 gcp-local:dev
curl http://localhost:4510/_emulator/health
```

For Kubernetes, Rancher Desktop, persistence, and service-selection details, see [`docs/deployment.md`](docs/deployment.md).

### Connect a BigQuery client

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

## Services

| Service        | Status    | Docs |
|----------------|-----------|------|
| BigQuery       | Alpha     | [docs/services/bigquery.md](docs/services/bigquery.md) |
| GCS            | Alpha     | [docs/services/gcs.md](docs/services/gcs.md) |
| Secret Manager | Alpha     | TODO |

## Configuration

| Variable                    | Default | Description |
|-----------------------------|---------|-------------|
| `SERVICES`                  | all     | Comma-separated list of services to start (e.g. `bigquery,gcs`) |
| `PERSIST`                   | `0`     | Set to `1` to persist state to `/data/` on disk |
| `BIGQUERY_EMULATOR_PORT`    | `9050`  | Override the BigQuery service port |
| `GCS_EMULATOR_PORT`         | `4443`  | Override the GCS service port |
| `SECRET_MANAGER_EMULATOR_PORT` | `8086` | Override the Secret Manager service port |

The admin API is on port `4510`. Reset all state without restarting:

```bash
curl -X POST http://localhost:4510/_emulator/reset
```

Reset a single service:

```bash
curl -X POST 'http://localhost:4510/_emulator/reset?service=bigquery'
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run all tests
pytest

# Run only integration tests
pytest tests/integration/

# Linting and type checks
ruff check .
ruff format --check .
mypy
```

## Disclaimer

gcp-local is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by Google LLC or Google Cloud. "Google Cloud Platform," "GCP," and related product names are trademarks of Google LLC.

## License

Apache 2.0.
