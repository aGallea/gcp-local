import pytest

from gcp_local.services.secret_manager.names import (
    InvalidResourceName,
    build_secret_name,
    build_version_name,
    parse_secret_name,
    parse_version_name,
    validate_secret_id,
)


def test_parse_secret_name():
    project, sid = parse_secret_name("projects/p1/secrets/db-password")
    assert project == "p1"
    assert sid == "db-password"


def test_parse_version_name():
    project, sid, vid = parse_version_name("projects/p1/secrets/db-password/versions/2")
    assert (project, sid, vid) == ("p1", "db-password", "2")


def test_parse_version_name_latest():
    project, sid, vid = parse_version_name("projects/p1/secrets/x/versions/latest")
    assert vid == "latest"


def test_build_secret_name():
    assert build_secret_name("p1", "my-secret") == "projects/p1/secrets/my-secret"


def test_build_version_name():
    assert build_version_name("p1", "my-secret", 3) == "projects/p1/secrets/my-secret/versions/3"


def test_build_version_name_latest():
    assert build_version_name("p1", "my-secret", "latest") == "projects/p1/secrets/my-secret/versions/latest"


def test_parse_secret_name_rejects_malformed():
    bad = [
        "",
        "projects/p1",
        "projects/p1/secrets/",
        "secrets/p1",
        "projects/p1/secrets/x/versions/1",
    ]
    for name in bad:
        with pytest.raises(InvalidResourceName):
            parse_secret_name(name)


def test_parse_version_name_rejects_malformed():
    bad = [
        "projects/p/secrets/x",
        "projects/p/secrets/x/versions/",
    ]
    for name in bad:
        with pytest.raises(InvalidResourceName):
            parse_version_name(name)


def test_validate_secret_id_happy():
    for ok in ("abc", "abc-123", "abc_123", "ABC", "A"):
        validate_secret_id(ok)


def test_validate_secret_id_rejects():
    for bad in ("", "a/b", "a.b", "a b", "a" * 256):
        with pytest.raises(InvalidResourceName):
            validate_secret_id(bad)
