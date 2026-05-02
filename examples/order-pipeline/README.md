# Order-Pipeline E2E Example

A runnable end-to-end example that uses every gcp-local service together to model a tiny order-processing pipeline. Built as both a teaching artifact and the e2e test that runs in CI on every pull request.

## What this is

Each call to `place_order(...)` exercises five services:

1. **Secret Manager** — looks up the payment-API key.
2. **Firestore** — writes the order doc with `status: pending`.
3. **GCS** — uploads a plaintext invoice to `gs://orders/orders/<id>/invoice.txt`.
4. **BigQuery** — inserts an analytics row into `demo-project.orders.events`.
5. **Pub/Sub** — publishes a notification message to `order-events`.

`confirm_pending_orders()` pulls those messages and updates each Firestore doc to `status: confirmed`. `daily_totals()` runs a SQL aggregate against BigQuery.

## Prerequisites

- Docker (with `docker compose`) and Python 3.13+.
- The five official Google Cloud Python clients:
  ```
  pip install google-cloud-bigquery google-cloud-storage \
              google-cloud-secret-manager google-cloud-pubsub \
              google-cloud-firestore
  ```
  (Or `pip install -e ".[dev]"` from the gcp-local repo root — these are already in dev deps.)

## Run it

From this directory:

```bash
docker compose up -d --build
python main.py
```

Expected last lines:

```
Daily totals (BigQuery aggregate):
  bob       112.25
  carol      77.00
  alice      61.25
```

When done:

```bash
docker compose down -v
```

## Walkthrough

| Method | Service | Purpose |
|---|---|---|
| `OrderPipeline.__init__` | admin API | Sets `*_EMULATOR_HOST` env vars; polls `/_emulator/health` until ok. |
| `setup()` | all five | Idempotent: seeds the secret, creates the GCS bucket, BigQuery dataset/table, and Pub/Sub topic+subscription. |
| `place_order(...)` | all five | One call per order — hits each service in the order shown above. |
| `confirm_pending_orders(...)` | Pub/Sub + Firestore | Pulls notification messages, updates docs to `confirmed`, acks. |
| `daily_totals()` | BigQuery | `GROUP BY customer SUM(amount)`. |

## Adapt this to your project

The pattern that lets the official client libraries auto-discover the emulator is the per-service `*_EMULATOR_HOST` environment variable plus `AnonymousCredentials`:

```python
import os
from google.auth import credentials as ga_credentials
from google.cloud import bigquery

os.environ["BIGQUERY_EMULATOR_HOST"] = "localhost:9050"
client = bigquery.Client(
    project="my-project",
    credentials=ga_credentials.AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:9050"},
)
```

Per-service usage docs: see [`docs/services/`](../../docs/services/) for the canonical recipe per service.

## CI

This example is the source for [`.github/workflows/e2e.yml`](../../.github/workflows/e2e.yml), which runs `pytest test_e2e.py` against a freshly-built gcp-local container on every non-draft pull request.
