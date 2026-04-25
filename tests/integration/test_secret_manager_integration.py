"""Integration tests driving the emulator with the real google-cloud-secret-manager client."""

import asyncio

import grpc
import pytest
from google.api_core import exceptions as gce
from google.cloud import secretmanager_v1
from google.cloud.secretmanager_v1.services.secret_manager_service.transports.grpc import (
    SecretManagerServiceGrpcTransport,
)
from google.protobuf.field_mask_pb2 import FieldMask


@pytest.fixture
def client(emulator):
    channel = grpc.insecure_channel(f"127.0.0.1:{emulator['secret_manager_port']}")
    transport = SecretManagerServiceGrpcTransport(channel=channel)
    return secretmanager_v1.SecretManagerServiceClient(transport=transport)


async def test_create_get_list_delete_secret(client):
    parent = "projects/p1"
    secret = secretmanager_v1.Secret(labels={"env": "dev"})
    created = await asyncio.to_thread(
        client.create_secret,
        request={"parent": parent, "secret_id": "my-secret", "secret": secret},
    )
    assert created.name == "projects/p1/secrets/my-secret"
    assert dict(created.labels) == {"env": "dev"}

    got = await asyncio.to_thread(client.get_secret, request={"name": created.name})
    assert got.name == created.name

    listed = await asyncio.to_thread(lambda: list(client.list_secrets(request={"parent": parent})))
    assert any(s.name == created.name for s in listed)

    await asyncio.to_thread(client.delete_secret, request={"name": created.name})
    with pytest.raises(gce.NotFound):
        await asyncio.to_thread(client.get_secret, request={"name": created.name})


async def test_add_and_access_secret_version(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    added = await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"hello"}},
    )
    assert added.name == f"{parent}/secrets/s/versions/1"
    accessed = await asyncio.to_thread(client.access_secret_version, request={"name": added.name})
    assert accessed.payload.data == b"hello"
    assert accessed.payload.data_crc32c != 0


async def test_access_latest_alias_returns_newest_enabled(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"v1"}},
    )
    await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"v2"}},
    )
    latest = await asyncio.to_thread(
        client.access_secret_version,
        request={"name": f"{parent}/secrets/s/versions/latest"},
    )
    assert latest.payload.data == b"v2"


async def test_disable_destroy_blocks_access(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    v = await asyncio.to_thread(
        client.add_secret_version,
        request={"parent": f"{parent}/secrets/s", "payload": {"data": b"secret"}},
    )
    await asyncio.to_thread(client.disable_secret_version, request={"name": v.name})
    with pytest.raises(gce.FailedPrecondition):
        await asyncio.to_thread(client.access_secret_version, request={"name": v.name})
    await asyncio.to_thread(client.enable_secret_version, request={"name": v.name})
    again = await asyncio.to_thread(client.access_secret_version, request={"name": v.name})
    assert again.payload.data == b"secret"
    await asyncio.to_thread(client.destroy_secret_version, request={"name": v.name})
    with pytest.raises(gce.FailedPrecondition):
        await asyncio.to_thread(client.access_secret_version, request={"name": v.name})


async def test_update_secret_labels_only(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(labels={"old": "1"}),
        },
    )
    updated = await asyncio.to_thread(
        client.update_secret,
        request={
            "secret": secretmanager_v1.Secret(
                name=f"{parent}/secrets/s",
                labels={"new": "2"},
                annotations={"ann": "x"},
            ),
            "update_mask": FieldMask(paths=["labels"]),
        },
    )
    assert dict(updated.labels) == {"new": "2"}
    assert dict(updated.annotations) == {}


async def test_list_secret_versions(client):
    parent = "projects/p1"
    await asyncio.to_thread(
        client.create_secret,
        request={
            "parent": parent,
            "secret_id": "s",
            "secret": secretmanager_v1.Secret(),
        },
    )
    for _ in range(3):
        await asyncio.to_thread(
            client.add_secret_version,
            request={"parent": f"{parent}/secrets/s", "payload": {"data": b"p"}},
        )
    versions = await asyncio.to_thread(
        lambda: list(client.list_secret_versions(request={"parent": f"{parent}/secrets/s"}))
    )
    ids = sorted(int(v.name.rsplit("/", 1)[1]) for v in versions)
    assert ids == [1, 2, 3]


async def test_get_secret_not_found_raises(client):
    with pytest.raises(gce.NotFound):
        await asyncio.to_thread(client.get_secret, request={"name": "projects/p1/secrets/nope"})
