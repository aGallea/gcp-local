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
        """Idempotent service setup. Subsequent tasks fill this in per-service."""
        return None
