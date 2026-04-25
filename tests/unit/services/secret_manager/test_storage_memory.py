import pytest

from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersionState,
)
from gcp_local.services.secret_manager.storage import (
    InMemoryStorage,
    InvalidStateTransition,
    SecretAlreadyExists,
    SecretNotFound,
    VersionNotFound,
)


def make_record(project="p", secret_id="s") -> SecretRecord:
    return SecretRecord(
        project=project,
        secret_id=secret_id,
        labels={},
        annotations={},
        create_time="t",
    )


async def test_create_and_get_secret():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="mine"))
    got = await s.get_secret("p", "mine")
    assert got.secret_id == "mine"


async def test_create_duplicate_raises():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    with pytest.raises(SecretAlreadyExists):
        await s.create_secret(make_record(secret_id="x"))


async def test_get_missing_raises():
    s = InMemoryStorage()
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "nope")


async def test_list_secrets_sorted_by_id():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="b"))
    await s.create_secret(make_record(secret_id="a"))
    items, _ = await s.list_secrets("p")
    assert [r.secret_id for r in items] == ["a", "b"]


async def test_list_secrets_scoped_to_project():
    s = InMemoryStorage()
    await s.create_secret(make_record(project="p1", secret_id="a"))
    await s.create_secret(make_record(project="p2", secret_id="b"))
    items, _ = await s.list_secrets("p1")
    assert [r.secret_id for r in items] == ["a"]


async def test_update_secret_replaces_labels():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    rec = await s.get_secret("p", "x")
    rec.labels = {"env": "dev"}
    await s.update_secret(rec)
    got = await s.get_secret("p", "x")
    assert got.labels == {"env": "dev"}


async def test_delete_secret_removes_it():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.delete_secret("p", "x")
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "x")


async def test_delete_missing_raises():
    s = InMemoryStorage()
    with pytest.raises(SecretNotFound):
        await s.delete_secret("p", "x")


async def test_add_version_starts_at_1_and_increments():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    v1 = await s.add_version("p", "x", b"a")
    v2 = await s.add_version("p", "x", b"b")
    assert v1.id == 1 and v2.id == 2
    assert v1.state == SecretVersionState.ENABLED
    assert v1.data_crc32c != 0


async def test_add_version_ids_do_not_recycle_after_destroy():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"a")
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    v2 = await s.add_version("p", "x", b"b")
    assert v2.id == 2


async def test_get_version():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"hi")
    v = await s.get_version("p", "x", 1)
    assert v.payload == b"hi"


async def test_get_missing_version_raises():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    with pytest.raises(VersionNotFound):
        await s.get_version("p", "x", 99)


async def test_list_versions_ordered_ascending():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    for i in range(3):
        await s.add_version("p", "x", f"v{i}".encode())
    items, _ = await s.list_versions("p", "x")
    assert [v.id for v in items] == [1, 2, 3]


async def test_update_version_state_transitions():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"hi")
    await s.update_version_state("p", "x", 1, SecretVersionState.DISABLED)
    v = await s.get_version("p", "x", 1)
    assert v.state == SecretVersionState.DISABLED
    await s.update_version_state("p", "x", 1, SecretVersionState.ENABLED)
    v = await s.get_version("p", "x", 1)
    assert v.state == SecretVersionState.ENABLED
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    v = await s.get_version("p", "x", 1)
    assert v.state == SecretVersionState.DESTROYED
    assert v.payload == b""
    assert v.destroy_time is not None


async def test_transitions_from_destroyed_forbidden():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.add_version("p", "x", b"hi")
    await s.update_version_state("p", "x", 1, SecretVersionState.DESTROYED)
    with pytest.raises(InvalidStateTransition):
        await s.update_version_state("p", "x", 1, SecretVersionState.ENABLED)


async def test_reset():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="x"))
    await s.reset()
    with pytest.raises(SecretNotFound):
        await s.get_secret("p", "x")


async def test_pagination():
    s = InMemoryStorage()
    await s.create_secret(make_record(secret_id="a"))
    await s.create_secret(make_record(secret_id="b"))
    await s.create_secret(make_record(secret_id="c"))
    page1, token = await s.list_secrets("p", page_size=2)
    assert [r.secret_id for r in page1] == ["a", "b"]
    assert token is not None
    page2, token2 = await s.list_secrets("p", page_size=2, page_token=token)
    assert [r.secret_id for r in page2] == ["c"]
    assert token2 is None
