import shutil
import subprocess
import time

import httpx
import pytest


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")

IMAGE = "gcp-local:dev"


@pytest.fixture
def docker_emulator():
    # Assumes the image has already been built. CI builds it before running tests.
    cid = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "-e",
            "SERVICES=gcs",
            "-p",
            "4510:4510",
            IMAGE,
        ],
        text=True,
    ).strip()
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = httpx.get("http://127.0.0.1:4510/_emulator/health", timeout=1)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("emulator container did not become healthy in time")
        yield "http://127.0.0.1:4510"
    finally:
        subprocess.run(["docker", "stop", cid], check=False)


def test_docker_image_health(docker_emulator):
    r = httpx.get(f"{docker_emulator}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "gcs" in body["services"]


def test_docker_image_serves_ui_bundle(docker_emulator):
    """The image must ship the built SPA bundle at ``/ui/``."""
    r = httpx.get(f"{docker_emulator}/ui/", follow_redirects=True, timeout=10)
    assert r.status_code == 200
    text = r.text.lower()
    assert "<html" in text
    # The fallback page contains "npm run build"; the real bundle does not.
    assert "npm run build" not in text


def test_docker_image_ui_api_round_trip(docker_emulator):
    """The internal ui-api namespace must respond inside the container."""
    r = httpx.get(f"{docker_emulator}/_emulator/ui-api/v1/services", timeout=10)
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["services"]}
    assert "gcs" in names


def test_docker_image_ui_deep_link_falls_back_to_index(docker_emulator):
    """Refreshing on a SPA route (e.g. /ui/gcs) must serve index.html, not 404."""
    r = httpx.get(f"{docker_emulator}/ui/gcs", timeout=10)
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_docker_image_bigquery_health():
    """BigQuery service should report healthy when started via SERVICES=bigquery."""
    # BQ default port is 9050; admin is 4510.  Map both so we can check health.
    cid = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "-e",
            "SERVICES=bigquery",
            "-p",
            "4511:4510",  # admin on 4511 to avoid conflict with the main fixture
            "-p",
            "9050:9050",  # BQ REST port
            IMAGE,
        ],
        text=True,
    ).strip()
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = httpx.get("http://127.0.0.1:4511/_emulator/health", timeout=1)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("bigquery container did not become healthy in time")
        r = httpx.get("http://127.0.0.1:4511/_emulator/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "bigquery" in body["services"]
        # Also verify the BQ REST port responds.
        r2 = httpx.get("http://127.0.0.1:9050/")
        assert r2.status_code == 200
        assert r2.json()["service"] == "bigquery"
    finally:
        subprocess.run(["docker", "stop", cid], check=False)
