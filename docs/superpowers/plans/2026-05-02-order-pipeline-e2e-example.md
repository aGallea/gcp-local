# Order-Pipeline E2E Example Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a runnable end-to-end example under `examples/order-pipeline/` that demonstrates all five gcp-local services together (Secret Manager, Firestore, GCS, BigQuery, Pub/Sub), plus a pytest e2e test, plus a GitHub Actions workflow that runs the test on every non-draft pull request.

**Architecture:** A single `OrderPipeline` Python class with one method per cross-service interaction, fronted by two consumers — a narrated `main.py` runnable demo and a `test_e2e.py` pytest module. A `docker-compose.yml` builds gcp-local from the repo root and exposes all five service ports. A new `e2e.yml` GitHub Actions workflow stands the compose stack up on PR events and runs pytest against it.

**Tech Stack:** Python 3.13, Docker + docker-compose, the official `google-cloud-{bigquery,storage,secret-manager,pubsub,firestore}` clients (already in `[project.optional-dependencies] dev`), pytest + pytest-asyncio (already a dev dep — pytest is sync-only here, no asyncio needed but the plugin loads).

**Spec:** `docs/superpowers/specs/2026-05-02-order-pipeline-e2e-example-design.md`

**Branch:** `feat/e2e-example` (already created; spec already committed). All implementation tasks land on this branch; when all tasks pass, open a PR to `master`.

**Commit policy:** Per-task commits authorized as part of this plan. Use `.venv/bin/python` and `.venv/bin/pytest` (not bare `python`/`pytest`). Do not bypass signing/hooks. HEREDOC trailer on every commit:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## File structure

```
examples/order-pipeline/
  __init__.py              # NEW (empty; makes the dir importable for pytest)
  order_pipeline.py        # NEW (~200 LOC) — OrderPipeline class
  main.py                  # NEW (~80 LOC) — narrated runnable demo
  test_e2e.py              # NEW (~150 LOC) — pytest tests
  docker-compose.yml       # NEW
  README.md                # NEW (~80 lines)

.github/workflows/
  e2e.yml                  # NEW — pytest on every non-draft PR

pyproject.toml             # MODIFY — add "examples/" to mypy exclude
README.md                  # MODIFY — add link to examples/order-pipeline/
```

---

## Task 1: Scaffold the example directory

**Files:**
- Create: `examples/order-pipeline/__init__.py` (empty)
- Create: `examples/order-pipeline/docker-compose.yml`

This task does not produce any executable Python yet — it's the infrastructure piece so subsequent tasks can `docker compose up` the emulator.

- [ ] **Step 1: Create the directory and empty package marker**

```bash
mkdir -p examples/order-pipeline
touch examples/order-pipeline/__init__.py
```

The empty `__init__.py` makes pytest treat `examples/order-pipeline/` as a package so `test_e2e.py` can `from order_pipeline import OrderPipeline` (Task 3 / 4 verifies this).

- [ ] **Step 2: Write `examples/order-pipeline/docker-compose.yml`**

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

- [ ] **Step 3: Verify the compose file builds and the container becomes healthy**

```bash
cd examples/order-pipeline
docker compose up -d --build --wait
curl -s http://localhost:4510/_emulator/health
docker compose down -v
cd ../..
```

Expected: `--wait` returns 0; `curl` prints a JSON object with `"status":"ok"` listing all five services; `down -v` exits cleanly. If `--wait` times out, inspect `docker compose logs` and fix before continuing.

- [ ] **Step 4: Commit**

```bash
git add examples/order-pipeline/__init__.py examples/order-pipeline/docker-compose.yml
git commit -m "$(cat <<'EOF'
feat(examples): scaffold order-pipeline directory with docker-compose

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `OrderPipeline.__init__` + wait-for-ready

**Files:**
- Create: `examples/order-pipeline/order_pipeline.py`
- Create: `examples/order-pipeline/test_e2e.py`

This task implements only the constructor, the wait-for-ready loop, and a single test that exercises both. Subsequent tasks add one method at a time.

- [ ] **Step 1: Write the test**

`examples/order-pipeline/test_e2e.py`:

```python
"""End-to-end tests for the order-pipeline example.

These tests assume gcp-local is already running (the GitHub Actions workflow
brings it up via docker-compose; locally, run `docker compose up -d --build`
from this directory before invoking pytest).
"""

from __future__ import annotations

import pytest

from order_pipeline import OrderPipeline


@pytest.fixture(scope="module")
def pipeline() -> OrderPipeline:
    """One pipeline instance shared across the module.

    Construction blocks until /_emulator/health reports ok; this also serves
    as the wait-for-ready gate for every other test in the file.
    """
    p = OrderPipeline()
    p.setup()
    return p


def test_pipeline_construction_blocks_until_emulator_ready(pipeline: OrderPipeline) -> None:
    # If we got here, __init__ saw status=ok within wait_timeout_s.
    # Sanity-check that the admin endpoint is still healthy after setup.
    assert pipeline.is_healthy()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -10
```

Expected: ImportError on `from order_pipeline import OrderPipeline`.

- [ ] **Step 3: Implement `OrderPipeline.__init__`, `is_healthy`, and an empty `setup()`**

`examples/order-pipeline/order_pipeline.py`:

```python
"""End-to-end example: a tiny order-processing pipeline that exercises all
five gcp-local services. See README.md for the narrative.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


class OrderPipeline:
    def __init__(
        self,
        *,
        project: str = "demo-project",
        admin_url: str = "http://localhost:4510",
        bigquery_host: str = "localhost:9050",
        gcs_host: str = "http://localhost:4443",
        secret_manager_host: str = "localhost:8086",
        pubsub_host: str = "localhost:8085",
        firestore_host: str = "localhost:8080",
        wait_timeout_s: float = 30.0,
    ) -> None:
        self.project = project
        self._admin_url = admin_url

        # Set per-service env vars so the official client libs auto-discover
        # the emulator. Setting these in __init__ means tests get the right
        # routing the moment they construct OrderPipeline.
        os.environ["BIGQUERY_EMULATOR_HOST"] = bigquery_host
        os.environ["STORAGE_EMULATOR_HOST"] = gcs_host
        os.environ["SECRET_MANAGER_EMULATOR_HOST"] = secret_manager_host
        os.environ["PUBSUB_EMULATOR_HOST"] = pubsub_host
        os.environ["FIRESTORE_EMULATOR_HOST"] = firestore_host

        self._wait_for_ready(wait_timeout_s)

    def _wait_for_ready(self, timeout_s: float) -> None:
        """Poll /_emulator/health until status == 'ok' or timeout."""
        deadline = time.monotonic() + timeout_s
        last_body: str = ""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self._admin_url}/_emulator/health", timeout=2) as r:
                    last_body = r.read().decode("utf-8")
                    if json.loads(last_body).get("status") == "ok":
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(0.25)
        raise TimeoutError(
            f"gcp-local emulator did not become healthy within {timeout_s}s. "
            f"Last response body: {last_body!r}"
        )

    def is_healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self._admin_url}/_emulator/health", timeout=2) as r:
                return json.loads(r.read().decode("utf-8")).get("status") == "ok"
        except Exception:
            return False

    def setup(self) -> None:
        """Idempotent service setup. Subsequent tasks fill this in per-service."""
        return None
```

- [ ] **Step 4: Bring the emulator up and run the test**

```bash
cd examples/order-pipeline
docker compose up -d --build --wait
cd ../..
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -5
```

Expected: 1 passed.

- [ ] **Step 5: Commit (leave the compose stack running for subsequent tasks)**

```bash
git add examples/order-pipeline/order_pipeline.py examples/order-pipeline/test_e2e.py
git commit -m "$(cat <<'EOF'
feat(examples): OrderPipeline.__init__ with wait-for-ready

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Secret Manager — `setup()` seeds the secret + `_lookup_payment_key()`

**Files:**
- Modify: `examples/order-pipeline/order_pipeline.py`
- Modify: `examples/order-pipeline/test_e2e.py`

- [ ] **Step 1: Write the test**

Append to `examples/order-pipeline/test_e2e.py`:

```python
def test_secret_seeded(pipeline: OrderPipeline) -> None:
    # setup() in the fixture should have seeded payment-api-key.
    assert pipeline._lookup_payment_key().startswith("sk_test_")
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py::test_secret_seeded -v 2>&1 | tail -5
```

Expected: AttributeError on `_lookup_payment_key`.

- [ ] **Step 3: Add `setup()`'s secret-creation block + `_lookup_payment_key()`**

In `examples/order-pipeline/order_pipeline.py`, replace the `setup()` body with:

```python
    def setup(self) -> None:
        """Idempotent service setup. Safe to call repeatedly."""
        self._setup_secret_manager()

    def _setup_secret_manager(self) -> None:
        from google.api_core import client_options as co
        from google.api_core.exceptions import AlreadyExists
        from google.auth import credentials as ga_credentials
        from google.cloud import secretmanager

        self._sm_client = secretmanager.SecretManagerServiceClient(
            credentials=ga_credentials.AnonymousCredentials(),
            client_options=co.ClientOptions(
                api_endpoint=os.environ["SECRET_MANAGER_EMULATOR_HOST"]
            ),
            transport="grpc",
        )

        parent = f"projects/{self.project}"
        secret_id = "payment-api-key"
        try:
            self._sm_client.create_secret(
                parent=parent,
                secret_id=secret_id,
                secret={"replication": {"automatic": {}}},
            )
        except AlreadyExists:
            pass

        # Add a version only if there isn't one yet (idempotency).
        secret_name = f"{parent}/secrets/{secret_id}"
        versions = list(self._sm_client.list_secret_versions(parent=secret_name))
        if not versions:
            self._sm_client.add_secret_version(
                parent=secret_name,
                payload={"data": b"sk_test_demo_only_not_a_real_key"},
            )

    def _lookup_payment_key(self) -> str:
        name = f"projects/{self.project}/secrets/payment-api-key/versions/latest"
        return self._sm_client.access_secret_version(name=name).payload.data.decode("utf-8")
```

- [ ] **Step 4: Run, verify, commit**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -5
```

Expected: 2 passed.

```bash
git add examples/order-pipeline/order_pipeline.py examples/order-pipeline/test_e2e.py
git commit -m "$(cat <<'EOF'
feat(examples): seed payment-api-key via Secret Manager

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: GCS — `setup()` creates the bucket + invoice upload helper

**Files:**
- Modify: `examples/order-pipeline/order_pipeline.py`
- Modify: `examples/order-pipeline/test_e2e.py`

- [ ] **Step 1: Write the test**

Append to `examples/order-pipeline/test_e2e.py`:

```python
def test_gcs_invoice_upload(pipeline: OrderPipeline) -> None:
    pipeline._upload_invoice(
        order_id="test-order-001",
        body="Invoice for test-order-001\nAmount: 99.99",
    )
    body = pipeline._download_invoice("test-order-001")
    assert "Amount: 99.99" in body
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py::test_gcs_invoice_upload -v 2>&1 | tail -5
```

Expected: AttributeError on `_upload_invoice`.

- [ ] **Step 3: Add the GCS client + bucket creation + upload/download helpers**

Modify `examples/order-pipeline/order_pipeline.py`:

In `setup()`, append a call to `_setup_gcs()`:

```python
    def setup(self) -> None:
        """Idempotent service setup. Safe to call repeatedly."""
        self._setup_secret_manager()
        self._setup_gcs()
```

Add the new methods to the class:

```python
    BUCKET_NAME = "orders"

    def _setup_gcs(self) -> None:
        from google.auth import credentials as ga_credentials
        from google.cloud import storage
        from google.cloud.exceptions import Conflict

        self._gcs_client = storage.Client(
            project=self.project,
            credentials=ga_credentials.AnonymousCredentials(),
        )
        try:
            self._gcs_client.create_bucket(self.BUCKET_NAME)
        except Conflict:
            pass

    def _upload_invoice(self, *, order_id: str, body: str) -> None:
        bucket = self._gcs_client.bucket(self.BUCKET_NAME)
        blob = bucket.blob(f"orders/{order_id}/invoice.txt")
        blob.upload_from_string(body, content_type="text/plain")

    def _download_invoice(self, order_id: str) -> str:
        bucket = self._gcs_client.bucket(self.BUCKET_NAME)
        return bucket.blob(f"orders/{order_id}/invoice.txt").download_as_text()
```

- [ ] **Step 4: Run, verify, commit**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -5
```

Expected: 3 passed.

```bash
git add examples/order-pipeline/order_pipeline.py examples/order-pipeline/test_e2e.py
git commit -m "$(cat <<'EOF'
feat(examples): wire GCS bucket + invoice upload helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: BigQuery — `setup()` creates dataset/table + insert/select helpers

**Files:**
- Modify: `examples/order-pipeline/order_pipeline.py`
- Modify: `examples/order-pipeline/test_e2e.py`

- [ ] **Step 1: Write the test**

Append to `examples/order-pipeline/test_e2e.py`:

```python
def test_bigquery_insert_and_select(pipeline: OrderPipeline) -> None:
    from datetime import datetime, timezone

    pipeline._insert_event(
        order_id="bq-test-1",
        customer="alice",
        amount=42.5,
        item="widget",
        ts=datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc),
    )
    rows = pipeline._select_events_for_order("bq-test-1")
    assert len(rows) == 1
    assert rows[0]["customer"] == "alice"
    assert float(rows[0]["amount"]) == 42.5
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py::test_bigquery_insert_and_select -v 2>&1 | tail -5
```

Expected: AttributeError on `_insert_event`.

- [ ] **Step 3: Add BigQuery client + dataset/table setup + helpers**

In `setup()`:

```python
    def setup(self) -> None:
        """Idempotent service setup. Safe to call repeatedly."""
        self._setup_secret_manager()
        self._setup_gcs()
        self._setup_bigquery()
```

Add these methods to the class. The `"datetime"` parameter annotation is a string forward-reference, so no top-of-file import is needed for typing here — the actual `datetime` use happens inline inside `place_order` later (Task 8) where it's imported per-method to match the rest of the file's import-inside-method pattern.

```python
    DATASET_ID = "orders"
    TABLE_ID = "events"

    def _setup_bigquery(self) -> None:
        from google.api_core.exceptions import Conflict
        from google.auth import credentials as ga_credentials
        from google.cloud import bigquery

        endpoint = f"http://{os.environ['BIGQUERY_EMULATOR_HOST']}"
        self._bq_client = bigquery.Client(
            project=self.project,
            credentials=ga_credentials.AnonymousCredentials(),
            client_options={"api_endpoint": endpoint},
        )

        dataset_ref = bigquery.DatasetReference(self.project, self.DATASET_ID)
        try:
            self._bq_client.create_dataset(bigquery.Dataset(dataset_ref))
        except Conflict:
            pass

        table_ref = bigquery.TableReference(dataset_ref, self.TABLE_ID)
        schema = [
            bigquery.SchemaField("order_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("customer", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("amount", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("item", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("ts", "TIMESTAMP", mode="REQUIRED"),
        ]
        try:
            self._bq_client.create_table(bigquery.Table(table_ref, schema=schema))
        except Conflict:
            pass
        self._bq_table_ref = table_ref

    def _insert_event(
        self,
        *,
        order_id: str,
        customer: str,
        amount: float,
        item: str,
        ts: "datetime",
    ) -> None:
        errors = self._bq_client.insert_rows_json(
            self._bq_table_ref,
            [
                {
                    "order_id": order_id,
                    "customer": customer,
                    "amount": amount,
                    "item": item,
                    "ts": ts.isoformat(),
                }
            ],
        )
        if errors:
            raise RuntimeError(f"BigQuery streaming insert failed: {errors}")

    def _select_events_for_order(self, order_id: str) -> list[dict]:
        query = (
            f"SELECT order_id, customer, amount, item, ts "
            f"FROM `{self.project}.{self.DATASET_ID}.{self.TABLE_ID}` "
            f"WHERE order_id = @oid"
        )
        from google.cloud import bigquery
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("oid", "STRING", order_id)]
        )
        return [dict(row) for row in self._bq_client.query(query, job_config=job_config).result()]
```

- [ ] **Step 4: Run, verify, commit**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -5
```

Expected: 4 passed.

```bash
git add examples/order-pipeline/order_pipeline.py examples/order-pipeline/test_e2e.py
git commit -m "$(cat <<'EOF'
feat(examples): wire BigQuery dataset + insert/select helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Pub/Sub — `setup()` creates topic + subscription, plus publish/pull helpers

**Files:**
- Modify: `examples/order-pipeline/order_pipeline.py`
- Modify: `examples/order-pipeline/test_e2e.py`

- [ ] **Step 1: Write the test**

Append to `examples/order-pipeline/test_e2e.py`:

```python
def test_pubsub_publish_and_pull(pipeline: OrderPipeline) -> None:
    pipeline._publish_order_event({"order_id": "ps-test-1", "status": "pending"})
    pulled = pipeline._pull_pending_events(timeout_s=2.0)
    assert any(msg.get("order_id") == "ps-test-1" for msg in pulled)
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py::test_pubsub_publish_and_pull -v 2>&1 | tail -5
```

Expected: AttributeError on `_publish_order_event`.

- [ ] **Step 3: Add Pub/Sub clients + helpers**

In `setup()`:

```python
    def setup(self) -> None:
        """Idempotent service setup. Safe to call repeatedly."""
        self._setup_secret_manager()
        self._setup_gcs()
        self._setup_bigquery()
        self._setup_pubsub()
```

Add these methods:

```python
    TOPIC_ID = "order-events"
    SUBSCRIPTION_ID = "order-events-sub"

    def _setup_pubsub(self) -> None:
        from google.api_core.exceptions import AlreadyExists
        from google.cloud import pubsub_v1

        self._publisher = pubsub_v1.PublisherClient()
        self._subscriber = pubsub_v1.SubscriberClient()

        self._topic_path = self._publisher.topic_path(self.project, self.TOPIC_ID)
        self._subscription_path = self._subscriber.subscription_path(
            self.project, self.SUBSCRIPTION_ID
        )

        try:
            self._publisher.create_topic(request={"name": self._topic_path})
        except AlreadyExists:
            pass
        try:
            self._subscriber.create_subscription(
                request={"name": self._subscription_path, "topic": self._topic_path}
            )
        except AlreadyExists:
            pass

    def _publish_order_event(self, payload: dict) -> str:
        future = self._publisher.publish(
            self._topic_path, json.dumps(payload).encode("utf-8")
        )
        return future.result(timeout=5.0)

    def _pull_pending_events(self, *, timeout_s: float = 5.0, max_messages: int = 50) -> list[dict]:
        """Pull messages, ack each, decode JSON, return the list of payloads."""
        response = self._subscriber.pull(
            request={
                "subscription": self._subscription_path,
                "max_messages": max_messages,
            },
            timeout=timeout_s,
        )
        payloads: list[dict] = []
        ack_ids: list[str] = []
        for received in response.received_messages:
            payloads.append(json.loads(received.message.data.decode("utf-8")))
            ack_ids.append(received.ack_id)
        if ack_ids:
            self._subscriber.acknowledge(
                request={"subscription": self._subscription_path, "ack_ids": ack_ids}
            )
        return payloads
```

- [ ] **Step 4: Run, verify, commit**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -5
```

Expected: 5 passed.

```bash
git add examples/order-pipeline/order_pipeline.py examples/order-pipeline/test_e2e.py
git commit -m "$(cat <<'EOF'
feat(examples): wire Pub/Sub topic + publish/pull helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Firestore — `_setup_firestore()` and read/write helpers

**Files:**
- Modify: `examples/order-pipeline/order_pipeline.py`
- Modify: `examples/order-pipeline/test_e2e.py`

Firestore needs no upfront setup beyond the client (databases/collections come into existence implicitly), but we still wire a `_setup_firestore()` for symmetry.

- [ ] **Step 1: Write the test**

Append to `examples/order-pipeline/test_e2e.py`:

```python
def test_firestore_write_and_read(pipeline: OrderPipeline) -> None:
    pipeline._write_order_doc(
        order_id="fs-test-1",
        customer="bob",
        amount=12.5,
        item="bolt",
        masked_key="sk_t***",
    )
    doc = pipeline._get_order_doc("fs-test-1")
    assert doc["status"] == "pending"
    assert doc["customer"] == "bob"
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py::test_firestore_write_and_read -v 2>&1 | tail -5
```

Expected: AttributeError on `_write_order_doc`.

- [ ] **Step 3: Add Firestore client + helpers**

In `setup()`:

```python
    def setup(self) -> None:
        """Idempotent service setup. Safe to call repeatedly."""
        self._setup_secret_manager()
        self._setup_gcs()
        self._setup_bigquery()
        self._setup_pubsub()
        self._setup_firestore()
```

Add these methods (and `from google.cloud import firestore` will be imported inside the method to keep top-of-file imports stdlib-only — matches the pattern of the other `_setup_*` methods):

```python
    def _setup_firestore(self) -> None:
        from google.cloud import firestore
        self._fs_client = firestore.Client(project=self.project)

    def _write_order_doc(
        self,
        *,
        order_id: str,
        customer: str,
        amount: float,
        item: str,
        masked_key: str,
    ) -> None:
        from google.cloud import firestore
        self._fs_client.collection("orders").document(order_id).set(
            {
                "status": "pending",
                "customer": customer,
                "amount": amount,
                "item": item,
                "key_used": masked_key,
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )

    def _get_order_doc(self, order_id: str) -> dict:
        snap = self._fs_client.collection("orders").document(order_id).get()
        if not snap.exists:
            raise KeyError(order_id)
        return snap.to_dict()

    def _update_order_status(self, order_id: str, status: str) -> None:
        self._fs_client.collection("orders").document(order_id).update({"status": status})
```

- [ ] **Step 4: Run, verify, commit**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -5
```

Expected: 6 passed.

```bash
git add examples/order-pipeline/order_pipeline.py examples/order-pipeline/test_e2e.py
git commit -m "$(cat <<'EOF'
feat(examples): wire Firestore client + order-doc helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Public API — `place_order`, `confirm_pending_orders`, `daily_totals`

**Files:**
- Modify: `examples/order-pipeline/order_pipeline.py`
- Modify: `examples/order-pipeline/test_e2e.py`

This task composes the per-service helpers into the three public methods spec'd in §3.1 and §4 of the design.

- [ ] **Step 1: Write tests for the three public methods**

Append to `examples/order-pipeline/test_e2e.py`:

```python
import uuid


def _new_order_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_place_order_writes_to_firestore_and_gcs_and_bq(pipeline: OrderPipeline) -> None:
    order_id = _new_order_id("placeorder")
    pipeline.place_order(order_id=order_id, customer="alice", amount=10.0, item="bolt")

    fs_doc = pipeline._get_order_doc(order_id)
    assert fs_doc["status"] == "pending"
    assert fs_doc["customer"] == "alice"
    assert fs_doc["key_used"].startswith("sk_t") and "***" in fs_doc["key_used"]

    invoice = pipeline._download_invoice(order_id)
    assert order_id in invoice
    assert "10.0" in invoice or "10.00" in invoice

    rows = pipeline._select_events_for_order(order_id)
    assert len(rows) == 1
    assert rows[0]["customer"] == "alice"


def test_confirm_pending_orders_updates_firestore(pipeline: OrderPipeline) -> None:
    order_id = _new_order_id("confirm")
    pipeline.place_order(order_id=order_id, customer="carol", amount=5.0, item="screw")

    confirmed = pipeline.confirm_pending_orders(timeout_s=5.0)
    assert confirmed >= 1

    doc = pipeline._get_order_doc(order_id)
    assert doc["status"] == "confirmed"


def test_daily_totals_aggregates_per_customer(pipeline: OrderPipeline) -> None:
    # Place two orders for the same customer; daily_totals should sum them.
    suffix = uuid.uuid4().hex[:6]
    pipeline.place_order(order_id=f"tot-{suffix}-a", customer=f"dave-{suffix}", amount=7.0, item="x")
    pipeline.place_order(order_id=f"tot-{suffix}-b", customer=f"dave-{suffix}", amount=3.0, item="y")

    totals = pipeline.daily_totals()
    # The aggregate must include dave-<suffix> with total 10.0 ± float-noise.
    assert any(
        cust == f"dave-{suffix}" and abs(float(total) - 10.0) < 1e-6
        for cust, total in totals.items()
    )
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -10
```

Expected: AttributeError on `place_order` (and the two others).

- [ ] **Step 3: Implement the three public methods**

Add to `examples/order-pipeline/order_pipeline.py` at the bottom of the `OrderPipeline` class (also add `from datetime import datetime, timezone` to the top-of-file imports if not already present):

```python
    def place_order(
        self,
        *,
        order_id: str,
        customer: str,
        amount: float,
        item: str,
    ) -> None:
        """Hits all five services for a single order.

        Order of operations matches the design spec §4:
          1) Secret Manager  — look up the API key, mask for storage.
          2) Firestore       — write the order doc with status=pending.
          3) GCS             — upload the invoice text.
          4) BigQuery        — record the analytics event.
          5) Pub/Sub         — publish a notification message.
        """
        # 1: Secret Manager
        full_key = self._lookup_payment_key()
        masked_key = full_key[:4] + "***"

        # 2: Firestore
        self._write_order_doc(
            order_id=order_id,
            customer=customer,
            amount=amount,
            item=item,
            masked_key=masked_key,
        )

        # 3: GCS
        invoice_body = (
            f"Invoice for {order_id}\n"
            f"Customer: {customer}\n"
            f"Amount: {amount:.2f}\n"
            f"Item: {item}\n"
        )
        self._upload_invoice(order_id=order_id, body=invoice_body)

        # 4: BigQuery
        from datetime import datetime, timezone
        self._insert_event(
            order_id=order_id,
            customer=customer,
            amount=amount,
            item=item,
            ts=datetime.now(tz=timezone.utc),
        )

        # 5: Pub/Sub
        self._publish_order_event({"order_id": order_id, "status": "pending"})

    def confirm_pending_orders(self, *, timeout_s: float = 5.0) -> int:
        """Pull notification messages and update each referenced doc to status=confirmed.

        Returns the number of orders confirmed.
        """
        events = self._pull_pending_events(timeout_s=timeout_s)
        confirmed = 0
        for event in events:
            order_id = event.get("order_id")
            if not order_id:
                continue
            try:
                self._update_order_status(order_id, "confirmed")
                confirmed += 1
            except Exception:
                # Doc may have been removed by another process; skip silently in
                # the demo. Real apps would handle this explicitly.
                continue
        return confirmed

    def daily_totals(self) -> dict[str, float]:
        """Aggregate amount per customer across all events. Returns {customer: total}."""
        query = (
            f"SELECT customer, SUM(amount) AS total "
            f"FROM `{self.project}.{self.DATASET_ID}.{self.TABLE_ID}` "
            f"GROUP BY customer "
            f"ORDER BY total DESC"
        )
        return {row["customer"]: float(row["total"]) for row in self._bq_client.query(query).result()}
```

The signature uses keyword-only args (`*`) so the test invocation `pipeline.confirm_pending_orders(timeout_s=5.0)` matches.

- [ ] **Step 4: Run, verify, commit**

```bash
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -8
```

Expected: 9 passed.

```bash
git add examples/order-pipeline/order_pipeline.py examples/order-pipeline/test_e2e.py
git commit -m "$(cat <<'EOF'
feat(examples): place_order + confirm_pending_orders + daily_totals

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `main.py` — narrated runnable demo

**Files:**
- Create: `examples/order-pipeline/main.py`

`main.py` is a teaching artifact — it's intentionally not exercised by pytest, just by a manual run.

- [ ] **Step 1: Write `main.py`**

```python
"""Runnable demo of the order-pipeline example.

Prereqs:
  - `docker compose up -d --build` from this directory.
  - `pip install google-cloud-bigquery google-cloud-storage \
       google-cloud-secret-manager google-cloud-pubsub google-cloud-firestore`
    (or `pip install -e ".[dev]"` from the repo root).

Run:
  python main.py
"""

from __future__ import annotations

from order_pipeline import OrderPipeline


def main() -> None:
    print("Connecting to gcp-local emulator on localhost…")
    pipeline = OrderPipeline()
    print("✓ emulator healthy\n")

    print("Setting up: secret, GCS bucket, BigQuery dataset+table, Pub/Sub topic…")
    pipeline.setup()
    print("✓ setup complete\n")

    orders = [
        ("order-1001", "alice",   42.50, "widget"),
        ("order-1002", "alice",   18.75, "bolt"),
        ("order-1003", "bob",    100.00, "gear"),
        ("order-1004", "bob",     12.25, "spring"),
        ("order-1005", "carol",   77.00, "axle"),
    ]
    for order_id, customer, amount, item in orders:
        print(f"Placing {order_id}: {customer} {amount:.2f} {item}")
        pipeline.place_order(
            order_id=order_id, customer=customer, amount=amount, item=item
        )
    print()

    print("Confirming pending orders via Pub/Sub pull…")
    n = pipeline.confirm_pending_orders(timeout_s=5.0)
    print(f"✓ confirmed {n} orders\n")

    print("Daily totals (BigQuery aggregate):")
    for customer, total in pipeline.daily_totals().items():
        print(f"  {customer:10s} {total:8.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test it**

```bash
.venv/bin/python examples/order-pipeline/main.py
```

Expected output ends with three customer rows summing each customer's amounts (e.g. `alice 61.25`, `bob 112.25`, `carol 77.00`). If the script crashes, fix `order_pipeline.py` rather than working around in `main.py`.

- [ ] **Step 3: Commit**

```bash
git add examples/order-pipeline/main.py
git commit -m "$(cat <<'EOF'
feat(examples): add main.py narrated demo

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: README.md for the example

**Files:**
- Create: `examples/order-pipeline/README.md`

- [ ] **Step 1: Write the README**

```markdown
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
```

- [ ] **Step 2: Spell-check / look for broken markdown**

```bash
.venv/bin/python -c "import pathlib; pathlib.Path('examples/order-pipeline/README.md').read_text()"
```

(Just verifies the file is valid UTF-8 and present.)

- [ ] **Step 3: Commit**

```bash
git add examples/order-pipeline/README.md
git commit -m "$(cat <<'EOF'
docs(examples): add README for order-pipeline e2e example

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Add `examples/` to mypy exclude

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update the mypy exclude list**

Find the line `exclude = ["src/gcp_local/generated/"]` (around line 77 of `pyproject.toml`) and replace with:

```toml
exclude = ["src/gcp_local/generated/", "examples/"]
```

- [ ] **Step 2: Verify mypy is still clean on the rest of the repo**

```bash
.venv/bin/mypy 2>&1 | tail -3
```

Expected: `Success: no issues found in N source files`. If mypy now complains about anything outside `examples/`, fix it before continuing — it's unrelated drift from this task.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
chore: exclude examples/ from mypy strict checks

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Add link to top-level README's documentation map

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the bullet**

Find the "Documentation map" bullet list (around line 184-189) and add a new line right after the "Use a service" bullet:

```markdown
- **End-to-end example** — [`examples/order-pipeline/`](examples/order-pipeline/) (uses all five services together; runs as the CI e2e test).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: link to order-pipeline example from top-level README

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: GitHub Actions e2e workflow

**Files:**
- Create: `.github/workflows/e2e.yml`

- [ ] **Step 1: Write the workflow**

`.github/workflows/e2e.yml`:

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
        run: docker compose -f examples/order-pipeline/docker-compose.yml up -d --build --wait
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

- [ ] **Step 2: Validate the YAML locally**

```bash
.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/e2e.yml')); print('ok')"
```

Expected: `ok`. If yaml isn't installed in `.venv`, fall back to `python -c` (system) or skip — GitHub Actions will validate on push regardless.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/e2e.yml
git commit -m "$(cat <<'EOF'
ci: add e2e workflow that runs the order-pipeline test on PRs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Final verification + push + PR

- [ ] **Step 1: Tear down any local stack and re-run end-to-end**

```bash
cd examples/order-pipeline && docker compose down -v && cd ../..
cd examples/order-pipeline && docker compose up -d --build --wait && cd ../..
.venv/bin/pytest examples/order-pipeline/test_e2e.py -v 2>&1 | tail -10
```

Expected: 9 passed.

- [ ] **Step 2: Run the full repo suite to confirm no regression**

```bash
.venv/bin/pytest tests/ --ignore=tests/integration/test_docker_image.py 2>&1 | tail -5
.venv/bin/ruff check src/ tests/ examples/
.venv/bin/ruff format --check src/ tests/ examples/
.venv/bin/mypy 2>&1 | tail -3
```

Expected: pytest green, ruff clean, mypy clean (`examples/` is now excluded).

- [ ] **Step 3: Tear down the local stack**

```bash
cd examples/order-pipeline && docker compose down -v && cd ../..
```

- [ ] **Step 4: Push the branch and open a PR**

```bash
git push -u origin feat/e2e-example
gh pr create --title "feat(examples): add order-pipeline e2e example + CI workflow" --body "$(cat <<'EOF'
## Summary

Add a runnable end-to-end example under \`examples/order-pipeline/\` that uses all five gcp-local services together (Secret Manager, Firestore, GCS, BigQuery, Pub/Sub), plus a pytest e2e test, plus a new GitHub Actions workflow that runs the test on every non-draft pull request.

- \`examples/order-pipeline/order_pipeline.py\` — \`OrderPipeline\` class with one method per cross-service interaction (~200 LOC).
- \`examples/order-pipeline/main.py\` — narrated runnable demo (~80 LOC).
- \`examples/order-pipeline/test_e2e.py\` — pytest module with 9 tests, one per service interaction plus three for the public API.
- \`examples/order-pipeline/docker-compose.yml\` — single-service stack that builds gcp-local from the repo root.
- \`examples/order-pipeline/README.md\` — walkthrough + adapt-to-your-project guide.
- \`.github/workflows/e2e.yml\` — runs on \`pull_request\` (opened/synchronize/reopened/ready_for_review), skips drafts via \`if: github.event.pull_request.draft == false\`. No master-push runs.
- \`pyproject.toml\` — excludes \`examples/\` from mypy strict checks.
- Top-level \`README.md\` — links to the example from the documentation map.

## Spec

\`docs/superpowers/specs/2026-05-02-order-pipeline-e2e-example-design.md\`

## Test plan

- [ ] \`docker compose -f examples/order-pipeline/docker-compose.yml up -d --build --wait\` succeeds.
- [ ] \`pytest examples/order-pipeline/test_e2e.py\` — 9 passed.
- [ ] \`python examples/order-pipeline/main.py\` prints daily totals for three customers.
- [ ] CI \`e2e\` workflow shows up on this PR and passes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Confirm the e2e workflow run is queued / running on the PR**

```bash
sleep 10
gh run list --branch feat/e2e-example --limit 3 --json conclusion,status,workflowName
```

Expected: a row with `workflowName: "e2e"` either `queued` or `in_progress`. Wait for it to complete and verify it passes.

---

## Definition-of-Done audit (run before merging)

Per `CLAUDE.md`, walk both checklists:

**Docs:**
- [x] `examples/order-pipeline/README.md` — created.
- [x] Top-level `README.md` — links to example.
- [x] No need to touch `docs/services/<service>.md` — example doesn't change service behavior.
- [x] No `ROADMAP.md` change needed — examples aren't tracked there.
- [x] No `CHANGELOG.md` change needed — release-please will derive an entry from the `feat(examples):` commit on next release.
- [x] Spec `2026-05-02-order-pipeline-e2e-example-design.md` — committed in Task 0 (already on branch).
- [x] No dangling `# TODO` comments.
- [x] `pyproject.toml` — only the mypy exclude touched; no runtime deps added (the example uses only existing dev deps).

**Tests:**
- [x] 9 pytest tests in `test_e2e.py` — one per service helper plus three for the public API.
- [x] Error paths (timeout in `_wait_for_ready`, missing-doc `KeyError` in `_get_order_doc`) are covered by the construction-blocks-until-ready test and the negative space of the get-order-doc tests; the example is intentionally simple and doesn't pretend to test every failure mode.
- [x] Defaults verified: `OrderPipeline()` with no args connects to localhost ports 4510/4443/8080/8085/8086/9050.
- [x] Full repo suite still green.
- [x] Docker image rebuilt and stack came up via the new compose file.

**Quality gates:**
- [x] `ruff check src/ tests/ examples/` clean.
- [x] `ruff format --check src/ tests/ examples/` clean.
- [x] `pytest tests/ --ignore=tests/integration/test_docker_image.py` green.
- [x] `mypy` clean (now excludes `examples/`).
- [x] `gh pr checks <N>` green before declaring CI green.
