import re


class InvalidResourceName(ValueError):
    pass


_SECRET_RE = re.compile(r"^projects/([^/]+)/secrets/([^/]+)$")
_VERSION_RE = re.compile(r"^projects/([^/]+)/secrets/([^/]+)/versions/([^/]+)$")
_SECRET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


def parse_secret_name(name: str) -> tuple[str, str]:
    m = _SECRET_RE.match(name)
    if not m:
        raise InvalidResourceName(f"not a secret name: {name!r}")
    project, secret_id = m.group(1), m.group(2)
    if not project or not secret_id:
        raise InvalidResourceName(f"empty segment in {name!r}")
    return project, secret_id


def parse_version_name(name: str) -> tuple[str, str, str]:
    m = _VERSION_RE.match(name)
    if not m:
        raise InvalidResourceName(f"not a version name: {name!r}")
    project, secret_id, version_id = m.group(1), m.group(2), m.group(3)
    if not project or not secret_id or not version_id:
        raise InvalidResourceName(f"empty segment in {name!r}")
    return project, secret_id, version_id


def build_secret_name(project: str, secret_id: str) -> str:
    return f"projects/{project}/secrets/{secret_id}"


def build_version_name(project: str, secret_id: str, version_id: int | str) -> str:
    return f"projects/{project}/secrets/{secret_id}/versions/{version_id}"


def validate_secret_id(secret_id: str) -> None:
    if not _SECRET_ID_RE.match(secret_id):
        raise InvalidResourceName(
            f"invalid secret id {secret_id!r}: must match [A-Za-z0-9_-]{{1,255}}"
        )
