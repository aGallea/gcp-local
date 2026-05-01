"""Path parsers and ID validators for Firestore resource names."""

import re

from gcp_local.services.firestore.errors import InvalidName

_DB_ROOT_RE = re.compile(r"^projects/([^/]+)/databases/([^/]+)$")
_DOC_PATH_RE = re.compile(r"^projects/([^/]+)/databases/([^/]+)/documents/(.+)$")
_RESERVED_COLLECTION_RE = re.compile(r"^__.*__$")


def parse_database_root(name: str) -> tuple[str, str]:
    m = _DB_ROOT_RE.match(name)
    if not m:
        raise InvalidName(f"invalid database root: {name}")
    project, database = m.group(1), m.group(2)
    if not project or not database:
        raise InvalidName(f"invalid database root: {name}")
    return project, database


def parse_document_path(name: str) -> tuple[str, str, str]:
    m = _DOC_PATH_RE.match(name)
    if not m:
        raise InvalidName(f"invalid document path: {name}")
    project, database, path = m.group(1), m.group(2), m.group(3)
    segments = path.split("/")
    if len(segments) % 2 != 0:
        raise InvalidName(f"document path must have even segment count: {name}")
    for seg in segments[::2]:
        validate_collection_id(seg)
    for seg in segments[1::2]:
        validate_document_id(seg)
    return project, database, path


def validate_document_id(doc_id: str) -> None:
    if not doc_id:
        raise InvalidName("document ID must be non-empty")
    if doc_id in (".", ".."):
        raise InvalidName(f"document ID cannot be {doc_id!r}")
    if "/" in doc_id:
        raise InvalidName("document ID cannot contain '/'")
    if len(doc_id.encode("utf-8")) > 1500:
        raise InvalidName("document ID exceeds 1500 bytes")


def validate_collection_id(coll_id: str) -> None:
    if not coll_id:
        raise InvalidName("collection ID must be non-empty")
    if "/" in coll_id:
        raise InvalidName("collection ID cannot contain '/'")
    if _RESERVED_COLLECTION_RE.match(coll_id):
        raise InvalidName(f"collection ID cannot match __.*__: {coll_id}")
    if len(coll_id.encode("utf-8")) > 1500:
        raise InvalidName("collection ID exceeds 1500 bytes")
