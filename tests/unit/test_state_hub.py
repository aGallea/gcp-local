import asyncio

import pytest

from gcp_local.core.state_hub import StateHub


async def test_publish_with_no_subscribers_is_noop():
    hub = StateHub()
    await hub.publish("nobody.listening", {"x": 1})  # should not raise


async def test_single_subscriber_receives_event():
    hub = StateHub()
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    hub.subscribe("gcs.object.created", handler)
    await hub.publish("gcs.object.created", {"bucket": "b", "name": "o"})
    assert received == [{"bucket": "b", "name": "o"}]


async def test_multiple_subscribers_all_receive():
    hub = StateHub()
    count = {"a": 0, "b": 0}

    async def ha(event: dict) -> None:
        count["a"] += 1

    async def hb(event: dict) -> None:
        count["b"] += 1

    hub.subscribe("topic", ha)
    hub.subscribe("topic", hb)
    await hub.publish("topic", {})
    assert count == {"a": 1, "b": 1}


async def test_handler_exception_does_not_stop_others():
    hub = StateHub()
    received: list[int] = []

    async def broken(event: dict) -> None:
        raise RuntimeError("boom")

    async def ok(event: dict) -> None:
        received.append(1)

    hub.subscribe("t", broken)
    hub.subscribe("t", ok)
    await hub.publish("t", {})
    assert received == [1]
