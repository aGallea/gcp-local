from gcp_local.services.secret_manager.models import (
    SecretRecord,
    SecretVersion,
    SecretVersionState,
)


def test_secret_version_state_values():
    assert SecretVersionState.ENABLED.value == "ENABLED"
    assert SecretVersionState.DISABLED.value == "DISABLED"
    assert SecretVersionState.DESTROYED.value == "DESTROYED"


def test_secret_version_defaults():
    v = SecretVersion(
        id=1,
        state=SecretVersionState.ENABLED,
        create_time="t",
        destroy_time=None,
        payload=b"p",
        data_crc32c=123,
    )
    assert v.id == 1
    assert v.destroy_time is None


def test_secret_record_defaults():
    r = SecretRecord(
        project="p",
        secret_id="s",
        labels={},
        annotations={},
        create_time="t",
        versions=[],
    )
    assert r.versions == []
    assert r.labels == {}


def test_secret_record_highest_enabled_version():
    r = SecretRecord(
        project="p",
        secret_id="s",
        labels={},
        annotations={},
        create_time="t",
        versions=[
            SecretVersion(
                id=1,
                state=SecretVersionState.ENABLED,
                create_time="t",
                destroy_time=None,
                payload=b"a",
                data_crc32c=0,
            ),
            SecretVersion(
                id=2,
                state=SecretVersionState.DISABLED,
                create_time="t",
                destroy_time=None,
                payload=b"b",
                data_crc32c=0,
            ),
            SecretVersion(
                id=3,
                state=SecretVersionState.ENABLED,
                create_time="t",
                destroy_time=None,
                payload=b"c",
                data_crc32c=0,
            ),
        ],
    )
    assert r.highest_enabled_version().id == 3


def test_secret_record_highest_enabled_version_none():
    r = SecretRecord(
        project="p",
        secret_id="s",
        labels={},
        annotations={},
        create_time="t",
        versions=[
            SecretVersion(
                id=1,
                state=SecretVersionState.DISABLED,
                create_time="t",
                destroy_time=None,
                payload=b"a",
                data_crc32c=0,
            ),
            SecretVersion(
                id=2,
                state=SecretVersionState.DESTROYED,
                create_time="t",
                destroy_time="t",
                payload=b"",
                data_crc32c=0,
            ),
        ],
    )
    assert r.highest_enabled_version() is None


def test_secret_record_get_version_by_id():
    r = SecretRecord(
        project="p",
        secret_id="s",
        labels={},
        annotations={},
        create_time="t",
        versions=[
            SecretVersion(
                id=1,
                state=SecretVersionState.ENABLED,
                create_time="t",
                destroy_time=None,
                payload=b"a",
                data_crc32c=0,
            ),
        ],
    )
    assert r.get_version(1).id == 1
    assert r.get_version(99) is None
