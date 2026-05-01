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
