import httpx


async def test_health_reports_gcs_service_healthy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "gcs" in body["services"]
    assert body["services"]["gcs"]["ok"] is True


async def test_services_endpoint_lists_gcs(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/services")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["services"]}
    assert "gcs" in names


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
