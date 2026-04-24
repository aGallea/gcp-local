import httpx


async def test_health_reports_dummy_service_healthy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "dummy" in body["services"]
    assert body["services"]["dummy"]["ok"] is True


async def test_services_endpoint_lists_dummy(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/_emulator/services")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["services"]}
    assert "dummy" in names


async def test_reset_all_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset")
    assert r.status_code == 204


async def test_reset_dummy_succeeds(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "dummy"})
    assert r.status_code == 204


async def test_reset_unknown_404(emulator):
    url = f"http://127.0.0.1:{emulator['admin_port']}"
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{url}/_emulator/reset", params={"service": "nope"})
    assert r.status_code == 404
