# Order-Pipeline E2E Example — Design

**Date:** 2026-05-02
**Status:** Draft for review
**Scope:** A runnable Python example that uses all five gcp-local services to model an order-processing pipeline, plus a pytest e2e test, plus a GitHub Actions workflow that runs the test on every non-draft PR.
**Related:** Per-service designs under `docs/superpowers/specs/`.

## 1. Overview

`gcp-local` ships five emulated services. This spec adds a single end-to-end **example** that demonstrates how to use all of them together — both as a teaching artifact for new users and as a CI smoke test that catches cross-service regressions.

The narrative is order processing: a tiny `OrderPipeline` class places synthetic orders, each of which exercises Secret Manager, Firestore, GCS, BigQuery, and Pub/Sub in turn. A runnable `main.py` demonstrates the flow with narrated output; a `test_e2e.py` runs the same `OrderPipeline` under pytest and asserts on the resulting state. A new GitHub Actions workflow stands up `gcp-local` via docker-compose and runs the pytest file on every non-draft pull request.

## 2. Scope

### 2.1 In scope

- A new `examples/order-pipeline/` directory containing:
  - `order_pipeline.py` — the `OrderPipeline` class with one method per cross-service interaction.
  - `main.py` — a narrated runnable demo (no pytest), placing 5 orders and printing the BigQuery aggregate at the end.
  - `test_e2e.py` — pytest tests exercising each service interaction independently.
  - `docker-compose.yml` — single-service compose file that builds the gcp-local container from the repo root.
  - `README.md` — walkthrough, prereqs, and an "adapt this to your project" section.
- A new `.github/workflows/e2e.yml` workflow:
  - Trigger: `pull_request` with `types: [opened, synchronize, reopened, ready_for_review]`.
  - Skip when the PR is in draft via `if: github.event.pull_request.draft == false`.
  - Build gcp-local image, run docker compose, install dev deps, run pytest, tear down on cleanup.
- Update `pyproject.toml` to exclude `examples/` from mypy strict checks (examples should read as straightforward demo code, not strict-typed).

### 2.2 Out of scope

- Multiple example scenarios. Only the order-pipeline story ships in this spec; future examples (e.g. `examples/log-ingestion/`) live under their own subdirectory and reuse the same workflow shape.
- Master-push or scheduled triggers for the workflow. PR-only.
- Real PDF generation for invoices. The example writes a fake plaintext invoice body to GCS to keep the example dependency-free.
- A standalone `requirements.txt` for the example. The repo's `[project.optional-dependencies] dev` already lists every needed client library; CI installs it via `pip install -e ".[dev]"`. The README lists the libs in prose for users adapting the example to a fresh project.
- Multi-arch CI runs. The publish-image workflow already builds multi-arch; this e2e workflow runs on `ubuntu-latest` (amd64) only.

## 3. Architecture

```
┌──────────────────────────────────────────────────────────┐
│  docker-compose                                           │
│    └─ gcp-local container (built from ../..)              │
│        SERVICES=bigquery,gcs,secret_manager,pubsub,firestore │
│        PERSIST=0                                          │
│        Ports: 4510 (admin), 4443, 8080, 8085, 8086, 9050  │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │ env vars + AnonymousCredentials
                          │
┌──────────────────────────────────────────────────────────┐
│  examples/order-pipeline/                                 │
│    order_pipeline.py    ← OrderPipeline class             │
│    main.py              ← runnable demo (place 5 orders)  │
│    test_e2e.py          ← pytest, one test per service    │
│    docker-compose.yml   ← spins up gcp-local              │
│    README.md            ← walkthrough                     │
└──────────────────────────────────────────────────────────┘
```

### 3.1 OrderPipeline class

```python
class OrderPipeline:
    def __init__(
        self,
        project: str = "demo-project",
        admin_url: str = "http://localhost:4510",
        # Per-service hosts default to the docker-compose port mapping.
        bigquery_host: str = "localhost:9050",
        gcs_host: str = "http://localhost:4443",
        secret_manager_host: str = "localhost:8086",
        pubsub_host: str = "localhost:8085",
        firestore_host: str = "localhost:8080",
        wait_timeout_s: float = 30.0,
    ) -> None:
        # Set per-service env vars so the official client libs auto-discover the emulator.
        # Poll admin_url/_emulator/health until status == "ok" or timeout.
        ...

    def setup(self) -> None:
        """Idempotent. Creates the secret, GCS bucket, BigQuery dataset+table,
        Pub/Sub topic+subscription. Safe to call repeatedly."""
        ...

    def place_order(self, order_id: str, customer: str, amount: float, item: str) -> None:
        """Hits all five services for a single order. See §4 for the step-by-step."""
        ...

    def confirm_pending_orders(self, timeout_s: float = 5.0) -> int:
        """Pulls Pub/Sub messages for the subscription and updates each
        referenced Firestore document's status from 'pending' to 'confirmed'.
        Returns the number of orders confirmed."""
        ...

    def daily_totals(self) -> dict[str, float]:
        """SELECT customer, SUM(amount) FROM orders.events GROUP BY customer.
        Returns {customer: total} dict, sorted by total descending."""
        ...

    def teardown(self) -> None:
        """No-op when PERSIST=0 — the docker-compose container is stateless.
        Provided so users adapting the example to PERSIST=1 can extend it."""
        ...
```

### 3.2 Wait-for-ready

`__init__` polls `GET {admin_url}/_emulator/health` once every 250ms until the response shows `status: ok` for every requested service, or up to `wait_timeout_s` (default 30s). On timeout, raises `TimeoutError` with the last response body. This avoids races where a client tries to connect before the gRPC server has bound its socket.

## 4. Data flow — `place_order(order_id, customer, amount, item)`

For each call, the pipeline performs these six steps in order. Each step uses the service's official Python client with `AnonymousCredentials` and the per-service env-var host.

1. **Secret Manager** — `access_secret_version(name="projects/demo-project/secrets/payment-api-key/versions/latest")`. The first 4 chars of the secret are remembered for the doc record (the rest are masked with `***`).
2. **Firestore** — `db.collection("orders").document(order_id).set({"status": "pending", "customer": customer, "amount": amount, "item": item, "key_used": "<masked>", "created_at": SERVER_TIMESTAMP})`.
3. **GCS** — `client.bucket("orders").blob(f"orders/{order_id}/invoice.txt").upload_from_string(invoice_text)`. The invoice body is a multi-line plaintext receipt (~200 bytes) that includes the order id, customer, amount, item, and a fake invoice number.
4. **BigQuery** — `client.insert_rows_json(table_ref, [{"order_id": order_id, "customer": customer, "amount": amount, "item": item, "ts": now_iso()}])` against `demo-project.orders.events`.
5. **Pub/Sub publish** — `publisher.publish(topic, json.dumps({"order_id": order_id, "status": "pending"}).encode("utf-8")).result()` (wait for the message-id to surface).
6. **Pub/Sub subscribe + Firestore update** — handled by `confirm_pending_orders()` rather than inline. Tests call it explicitly after placing all orders. The handler pulls messages with a short-poll, decodes the JSON body, updates the Firestore doc's `status` to `"confirmed"`, and acks. Returns the number of acks.

`daily_totals()` runs once at the end of `main.py` and inside `test_daily_totals_aggregate`:

```sql
SELECT customer, SUM(amount) AS total
FROM `demo-project.orders.events`
GROUP BY customer
ORDER BY total DESC
```

## 5. Tests (`test_e2e.py`)

Pytest, module-scope fixture spins up one `OrderPipeline` and calls `setup()` once. Tests share state intentionally (the BigQuery aggregate test depends on prior `place_order` calls) but each test uses a fresh `order_id` so they don't collide.

| Test | Asserts |
|---|---|
| `test_secret_seeded` | `access_secret_version` returns the expected value (the seeded API key). |
| `test_place_order_writes_to_firestore` | After `place_order(...)`, the Firestore doc exists with status `pending` and the right fields. |
| `test_place_order_uploads_invoice` | The GCS blob `orders/<order_id>/invoice.txt` exists and contains the order id and amount. |
| `test_place_order_inserts_bq_row` | A SELECT against `orders.events WHERE order_id = X` returns exactly one row. |
| `test_pubsub_confirms_pending_order` | After `place_order` + `confirm_pending_orders(timeout_s=5)`, the Firestore doc's status is `confirmed`. |
| `test_daily_totals_aggregate` | Place 3 additional orders for two customers, run `daily_totals()`, assert the aggregate dict matches `sum(amount per customer)`. |

Tests are written so a CI failure points at the specific service that broke. The pubsub-confirms test deliberately uses a 5-second timeout so it does not hang on a regression.

## 6. CI workflow `.github/workflows/e2e.yml`

```yaml
name: e2e

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  e2e:
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: docker/setup-buildx-action@v4
      - name: Start gcp-local via docker compose
        run: docker compose -f examples/order-pipeline/docker-compose.yml up -d --build
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -e ".[dev]"
      - name: Run e2e tests
        run: pytest examples/order-pipeline/test_e2e.py -v
      - name: Dump container logs on failure
        if: failure()
        run: docker compose -f examples/order-pipeline/docker-compose.yml logs --no-color
      - name: Tear down
        if: always()
        run: docker compose -f examples/order-pipeline/docker-compose.yml down -v
```

### 6.1 Trigger semantics

- Runs on `pull_request` only — no master-push runs, no scheduled runs.
- `types: [opened, synchronize, reopened, ready_for_review]` covers: new non-draft PR opened, new commit pushed to an open PR, closed→reopened, and draft→ready transitions.
- `if: github.event.pull_request.draft == false` skips drafts entirely. The workflow shows up as "skipped" in the PR's check list.
- Concurrency cancels superseded runs when a new commit is pushed.

### 6.2 Cleanup

`docker compose down -v` runs in an `if: always()` step so port allocations are freed even when tests fail. `docker compose logs` runs only on failure so successful runs don't bloat the log.

## 7. docker-compose.yml

```yaml
services:
  gcp-local:
    build:
      context: ../..
      dockerfile: docker/Dockerfile
    environment:
      SERVICES: "bigquery,gcs,secret_manager,pubsub,firestore"
      PERSIST: "0"
    ports:
      - "4510:4510"  # admin
      - "4443:4443"  # gcs
      - "8080:8080"  # firestore
      - "8085:8085"  # pubsub
      - "8086:8086"  # secret_manager
      - "9050:9050"  # bigquery
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,json,sys; r=json.load(urllib.request.urlopen('http://localhost:4510/_emulator/health')); sys.exit(0 if r.get('status')=='ok' else 1)\""]
      interval: 1s
      timeout: 2s
      retries: 30
      start_period: 2s
```

The healthcheck is defensive (CI also polls from the Python side) but lets `docker compose up -d --wait` block until the container is ready.

## 8. README.md

Sections:

1. **What this is** — one-paragraph summary of the order-pipeline narrative.
2. **Prerequisites** — Docker + Python ≥3.13 + the five client libraries (listed by name so a user adapting the example to their own project knows what to `pip install`).
3. **Run it** — `docker compose up -d --build && python main.py` with expected output excerpt.
4. **Walkthrough** — one paragraph per `OrderPipeline` method, naming the underlying service and the env var the official client reads.
5. **Adapt this to your project** — explains the env-var pattern (`<SERVICE>_EMULATOR_HOST`), `AnonymousCredentials`, and links to the per-service usage docs under `docs/services/`.
6. **CI** — one-line pointer to `.github/workflows/e2e.yml` for users curious about how the example runs in CI.

Aim for ~80 lines.

## 9. Configuration changes outside the example dir

- `pyproject.toml` — add `"examples/"` to `[tool.mypy] exclude`. Examples are demo code; stricter typing would clutter them with `# type: ignore` for non-stub clients.
- `README.md` (top-level) — add a one-line link in the "Documentation map" section pointing at `examples/order-pipeline/` so the example is discoverable.

## 10. Conventional Commit type and release-please impact

Branch: `feat/e2e-example`. Commit type: `feat(examples): add order-pipeline e2e example`. Per `release-please-config.json`, `feat` lands in the next CHANGELOG's `### Added` section. The bump will be a minor (currently pre-1.0; `bump-minor-pre-major: true`).

## 11. Internals-level limitations

- **No multi-arch test.** CI runs amd64-only; arm64 verification piggy-backs on the existing publish-image workflow.
- **State is shared across tests in a module.** The fixture is module-scoped to keep the run fast; tests use unique order IDs to avoid collisions, but a test that mutates shared state (e.g., deletes the secret) would break later tests in the file.
- **No retry on flake.** If a test fails due to a transient docker/host port collision, CI surfaces the failure rather than auto-retrying; that's intentional — quiet retries hide real regressions.
- **Healthcheck depends on the admin API.** If a future service breaks the `/_emulator/health` endpoint contract, the example breaks before tests even start. That's a feature; the example is a smoke test for the contract too.
