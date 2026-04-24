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


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="docker daemon not available"
)

IMAGE = "gcp-local:dev"


@pytest.fixture
def docker_emulator():
    # Assumes the image has already been built. CI builds it before running tests.
    cid = subprocess.check_output(
        [
            "docker", "run", "--rm", "-d",
            "-e", "SERVICES=dummy",
            "-p", "4510:4510",
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
    assert "dummy" in body["services"]
