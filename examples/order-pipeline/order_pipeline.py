"""End-to-end example: a tiny order-processing pipeline that exercises all
five gcp-local services. See README.md for the narrative.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


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
        """Poll /_emulator/health until ok=True or timeout."""
        deadline = time.monotonic() + timeout_s
        last_body: str = ""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self._admin_url}/_emulator/health", timeout=2) as r:
                    last_body = r.read().decode("utf-8")
                    if json.loads(last_body).get("ok") is True:
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
                return json.loads(r.read().decode("utf-8")).get("ok") is True
        except Exception:
            return False

    def setup(self) -> None:
        """Idempotent service setup. Safe to call repeatedly."""
        self._setup_secret_manager()
        self._setup_gcs()
        self._setup_bigquery()
        self._setup_pubsub()
        self._setup_firestore()

    def _setup_secret_manager(self) -> None:
        import contextlib

        import grpc
        from google.api_core.exceptions import AlreadyExists
        from google.cloud import secretmanager_v1
        from google.cloud.secretmanager_v1.services.secret_manager_service.transports.grpc import (
            SecretManagerServiceGrpcTransport,
        )

        channel = grpc.insecure_channel(os.environ["SECRET_MANAGER_EMULATOR_HOST"])
        transport = SecretManagerServiceGrpcTransport(channel=channel)
        self._sm_client = secretmanager_v1.SecretManagerServiceClient(transport=transport)

        parent = f"projects/{self.project}"
        secret_id = "payment-api-key"
        with contextlib.suppress(AlreadyExists):
            self._sm_client.create_secret(
                parent=parent,
                secret_id=secret_id,
                secret={"replication": {"automatic": {}}},
            )

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

    BUCKET_NAME = "orders"

    def _setup_gcs(self) -> None:
        import contextlib

        from google.auth import credentials as ga_credentials
        from google.cloud import storage
        from google.cloud.exceptions import Conflict

        self._gcs_client = storage.Client(
            project=self.project,
            credentials=ga_credentials.AnonymousCredentials(),
        )
        with contextlib.suppress(Conflict):
            self._gcs_client.create_bucket(self.BUCKET_NAME)

    def _upload_invoice(self, *, order_id: str, body: str) -> None:
        bucket = self._gcs_client.bucket(self.BUCKET_NAME)
        blob = bucket.blob(f"orders/{order_id}/invoice.txt")
        blob.upload_from_string(body, content_type="text/plain")

    def _download_invoice(self, order_id: str) -> str:
        bucket = self._gcs_client.bucket(self.BUCKET_NAME)
        return bucket.blob(f"orders/{order_id}/invoice.txt").download_as_text()

    DATASET_ID = "orders"
    TABLE_ID = "events"

    def _setup_bigquery(self) -> None:
        import contextlib

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
        with contextlib.suppress(Conflict):
            self._bq_client.create_dataset(bigquery.Dataset(dataset_ref))

        table_ref = bigquery.TableReference(dataset_ref, self.TABLE_ID)
        schema = [
            bigquery.SchemaField("order_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("customer", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("amount", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("item", "STRING", mode="REQUIRED"),
            # gcp-local's BigQuery emulator has a known issue reading TIMESTAMP
            # columns via the streaming-insert path; we store the timestamp as
            # an ISO-8601 STRING for the demo. Production code would normally
            # use TIMESTAMP here.
            bigquery.SchemaField("ts", "STRING", mode="REQUIRED"),
        ]
        with contextlib.suppress(Conflict):
            self._bq_client.create_table(bigquery.Table(table_ref, schema=schema))
        self._bq_table_ref = table_ref

    def _insert_event(
        self,
        *,
        order_id: str,
        customer: str,
        amount: float,
        item: str,
        ts: datetime,
    ) -> None:
        # The streaming-insert path (insert_rows_json) currently has timing
        # issues against gcp-local's BigQuery emulator. Use a plain INSERT
        # statement instead — same pattern the existing integration tests
        # use. Order ids and customer names are tightly controlled in this
        # demo (UUID hex / static test strings) but we still escape single
        # quotes defensively.
        def q(s: str) -> str:
            return s.replace("'", "''")

        sql = (
            f"INSERT INTO `{self.project}.{self.DATASET_ID}.{self.TABLE_ID}` "
            f"(order_id, customer, amount, item, ts) VALUES "
            f"('{q(order_id)}', '{q(customer)}', {amount}, '{q(item)}', '{ts.isoformat()}')"
        )
        self._bq_client.query(sql).result()

    def _select_events_for_order(self, order_id: str) -> list[dict]:
        # gcp-local's BigQuery emulator does not currently support parameterized
        # queries (`@oid`), so we interpolate manually. order_id is tightly
        # controlled in this demo (UUID hex or static test strings), but we
        # still escape single quotes defensively.
        safe = order_id.replace("'", "''")
        query = (
            f"SELECT order_id, customer, amount, item, ts "
            f"FROM `{self.project}.{self.DATASET_ID}.{self.TABLE_ID}` "
            f"WHERE order_id = '{safe}'"
        )
        return [dict(row) for row in self._bq_client.query(query).result()]

    TOPIC_ID = "order-events"
    SUBSCRIPTION_ID = "order-events-sub"

    def _setup_pubsub(self) -> None:
        import contextlib

        from google.api_core.exceptions import AlreadyExists
        from google.cloud import pubsub_v1

        self._publisher = pubsub_v1.PublisherClient()
        self._subscriber = pubsub_v1.SubscriberClient()

        self._topic_path = self._publisher.topic_path(self.project, self.TOPIC_ID)
        self._subscription_path = self._subscriber.subscription_path(
            self.project, self.SUBSCRIPTION_ID
        )

        with contextlib.suppress(AlreadyExists):
            self._publisher.create_topic(request={"name": self._topic_path})
        with contextlib.suppress(AlreadyExists):
            self._subscriber.create_subscription(
                request={"name": self._subscription_path, "topic": self._topic_path}
            )

    def _publish_order_event(self, payload: dict) -> str:
        future = self._publisher.publish(self._topic_path, json.dumps(payload).encode("utf-8"))
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

    def place_order(
        self,
        *,
        order_id: str,
        customer: str,
        amount: float,
        item: str,
    ) -> None:
        """Hits all five services for a single order:

        1) Secret Manager — look up the API key, mask for storage.
        2) Firestore       — write the order doc with status=pending.
        3) GCS             — upload the invoice text.
        4) BigQuery        — record the analytics event.
        5) Pub/Sub         — publish a notification message.
        """
        from datetime import datetime

        full_key = self._lookup_payment_key()
        masked_key = full_key[:4] + "***"

        self._write_order_doc(
            order_id=order_id,
            customer=customer,
            amount=amount,
            item=item,
            masked_key=masked_key,
        )

        invoice_body = (
            f"Invoice for {order_id}\nCustomer: {customer}\nAmount: {amount:.2f}\nItem: {item}\n"
        )
        self._upload_invoice(order_id=order_id, body=invoice_body)

        self._insert_event(
            order_id=order_id,
            customer=customer,
            amount=amount,
            item=item,
            ts=datetime.now(tz=UTC),
        )

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
        return {
            row["customer"]: float(row["total"]) for row in self._bq_client.query(query).result()
        }
