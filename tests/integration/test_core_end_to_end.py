import asyncio

import httpx


async def test_health_reports_both_services_healthy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["services"].keys()) == {"gcs", "secret_manager", "bigquery"}
    assert body["services"]["gcs"]["ok"] is True
    assert body["services"]["secret_manager"]["ok"] is True
    assert body["services"]["bigquery"]["ok"] is True


async def test_services_endpoint_lists_both(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/services")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["services"]}
    assert names == {"gcs", "secret_manager", "bigquery"}


async def test_reset_all_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset")
    assert r.status_code == 204


async def test_reset_gcs_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "gcs"})
    assert r.status_code == 204


async def test_reset_secret_manager_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "secret_manager"})
    assert r.status_code == 204


async def test_reset_unknown_404(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "nope"})
    assert r.status_code == 404


async def test_gcs_root_responds(emulator):
    url = f"http://127.0.0.1:{emulator['gcs_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/")
    assert r.status_code == 200
    assert r.json() == {"service": "gcs", "status": "ok"}


async def test_secret_manager_grpc_port_open(emulator):
    """The secret_manager port should accept TCP connections (gRPC server up)."""
    _, writer = await asyncio.open_connection("127.0.0.1", emulator["secret_manager_port"])
    writer.close()
    await writer.wait_closed()
