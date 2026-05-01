"""Firestore gRPC servicers — document CRUD RPCs (Task 6)."""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from google.protobuf import empty_pb2
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc
from gcp_local.generated.google.firestore.v1 import document_pb2, firestore_pb2, firestore_pb2_grpc
from gcp_local.services.firestore import errors, names
from gcp_local.services.firestore.models import DocumentRecord
from gcp_local.services.firestore.storage import FirestoreStorage
from gcp_local.services.firestore.values import from_proto, to_proto

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _mint_doc_id() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(20))


def _doc_to_proto(rec: DocumentRecord) -> document_pb2.Document:
    resource_name = f"projects/{rec.project}/databases/{rec.database}/documents/{rec.path}"
    fields = {k: to_proto(v) for k, v in rec.fields.items()}
    proto = document_pb2.Document(name=resource_name, fields=fields)
    proto.create_time.FromDatetime(rec.create_time)
    proto.update_time.FromDatetime(rec.update_time)
    return proto


def _fields_from_proto(proto: document_pb2.Document) -> dict[str, Any]:
    return {k: from_proto(v) for k, v in proto.fields.items()}


def _check_precondition(rec: DocumentRecord | None, precondition: Any) -> None:
    """Raise FailedPrecondition / DocumentAlreadyExists per Firestore semantics."""
    if not precondition or not precondition.WhichOneof("condition_type"):
        return
    which = precondition.WhichOneof("condition_type")
    if which == "exists":
        if precondition.exists and rec is None:
            raise errors.FailedPrecondition("document does not exist")
        if not precondition.exists and rec is not None:
            raise errors.FailedPrecondition("document already exists")
    elif which == "update_time":
        if rec is None:
            raise errors.FailedPrecondition("document does not exist")
        ut = Timestamp()
        ut.FromDatetime(rec.update_time)
        if (ut.seconds, ut.nanos) != (
            precondition.update_time.seconds,
            precondition.update_time.nanos,
        ):
            raise errors.FailedPrecondition("update_time mismatch")


def _parse_parent_for_list(parent: str) -> tuple[str, str, str]:
    """Parse a ListDocuments/ListCollectionIds parent into (project, database, doc_path).

    parent is one of:
      projects/<p>/databases/<db>/documents            -> doc_path = ""
      projects/<p>/databases/<db>/documents/<path>     -> doc_path = <path>
    """
    import re

    m = re.match(r"^projects/([^/]+)/databases/([^/]+)/documents(?:/(.+))?$", parent)
    if not m:
        raise errors.InvalidName(f"invalid parent: {parent!r}")
    project = m.group(1)
    database = m.group(2)
    doc_path = m.group(3) or ""
    return project, database, doc_path


# ---------------------------------------------------------------------------
# FirestoreServicer
# ---------------------------------------------------------------------------


class FirestoreServicer(firestore_pb2_grpc.FirestoreServicer):  # type: ignore[misc, name-defined]
    def __init__(self, storage: FirestoreStorage, state_hub: StateHub | None) -> None:
        self._storage = storage
        self._state_hub = state_hub

    # ------------------------------------------------------------------
    # GetDocument
    # ------------------------------------------------------------------

    async def GetDocument(self, request: Any, context: Any) -> Any:
        try:
            project, database, path = names.parse_document_path(request.name)
            rec = await self._storage.get_document(project, database, path)
            return _doc_to_proto(rec)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            raise  # unreachable; abort_with raises

    # ------------------------------------------------------------------
    # CreateDocument
    # ------------------------------------------------------------------

    async def CreateDocument(self, request: Any, context: Any) -> Any:
        try:
            # parent is "projects/<p>/databases/<db>/documents[/<path>]"
            project, database, parent_path = _parse_parent_for_list(request.parent)
            doc_id = request.document_id or _mint_doc_id()
            # Build the full path
            if parent_path:
                path = f"{parent_path}/{request.collection_id}/{doc_id}"
            else:
                path = f"{request.collection_id}/{doc_id}"

            # Validate the resulting path segments
            names.parse_document_path(f"projects/{project}/databases/{database}/documents/{path}")

            existing: DocumentRecord | None
            try:
                existing = await self._storage.get_document(project, database, path)
            except errors.DocumentNotFound:
                existing = None

            if existing is not None:
                raise errors.DocumentAlreadyExists(f"document {path!r} already exists")

            now = _now()
            version = await self._storage.next_version(project, database)
            rec = DocumentRecord(
                project=project,
                database=database,
                path=path,
                fields=_fields_from_proto(request.document),
                create_time=now,
                update_time=now,
                version=version,
            )
            await self._storage.put_document(rec)
            return _doc_to_proto(rec)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            raise

    # ------------------------------------------------------------------
    # UpdateDocument
    # ------------------------------------------------------------------

    async def UpdateDocument(self, request: Any, context: Any) -> Any:
        try:
            project, database, path = names.parse_document_path(request.document.name)

            existing: DocumentRecord | None
            try:
                existing = await self._storage.get_document(project, database, path)
            except errors.DocumentNotFound:
                existing = None

            # Honor current_document precondition
            if request.HasField("current_document"):
                _check_precondition(existing, request.current_document)

            mask = request.update_mask
            now = _now()
            version = await self._storage.next_version(project, database)

            if mask and list(mask.field_paths):
                # Merge: keep existing fields, overwrite only masked ones
                merged: dict[str, Any] = dict(existing.fields) if existing else {}
                incoming = _fields_from_proto(request.document)
                for field_path in mask.field_paths:
                    # Simple (non-nested) field paths — dotted paths handled by
                    # splitting on "." and walking the nested dict.
                    parts = field_path.split(".")
                    if len(parts) == 1:
                        field_name = parts[0]
                        if field_name in incoming:
                            merged[field_name] = incoming[field_name]
                        else:
                            # Field is in mask but not in request body → delete it
                            merged.pop(field_name, None)
                    else:
                        # Nested path: update sub-field
                        _set_nested(merged, parts, incoming)
                new_fields = merged
            else:
                # No mask → full replace
                new_fields = _fields_from_proto(request.document)

            create_time = existing.create_time if existing else now
            rec = DocumentRecord(
                project=project,
                database=database,
                path=path,
                fields=new_fields,
                create_time=create_time,
                update_time=now,
                version=version,
            )
            await self._storage.put_document(rec)
            return _doc_to_proto(rec)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            raise

    # ------------------------------------------------------------------
    # DeleteDocument
    # ------------------------------------------------------------------

    async def DeleteDocument(self, request: Any, context: Any) -> Any:
        try:
            project, database, path = names.parse_document_path(request.name)

            existing: DocumentRecord | None
            try:
                existing = await self._storage.get_document(project, database, path)
            except errors.DocumentNotFound:
                existing = None

            if request.HasField("current_document"):
                _check_precondition(existing, request.current_document)

            await self._storage.delete_document(project, database, path)
            return empty_pb2.Empty()
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            raise

    # ------------------------------------------------------------------
    # BatchGetDocuments  (server-streaming)
    # ------------------------------------------------------------------

    async def BatchGetDocuments(self, request: Any, context: Any) -> AsyncIterator[Any]:
        if request.transaction:
            await errors.abort_with(
                context, errors.Unimplemented("transactional BatchGetDocuments")
            )
            return

        try:
            # database field: "projects/<p>/databases/<db>"
            project, database = names.parse_database_root(request.database)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        names_list = list(request.documents)
        for doc_name in names_list:
            try:
                _, _, path = names.parse_document_path(doc_name)
                rec = await self._storage.get_document(project, database, path)
                yield firestore_pb2.BatchGetDocumentsResponse(found=_doc_to_proto(rec))
            except errors.DocumentNotFound:
                yield firestore_pb2.BatchGetDocumentsResponse(missing=doc_name)
            except errors.InvalidName as exc:
                await errors.abort_with(context, exc)
                return

        # Final response with read_time
        read_ts = Timestamp()
        read_ts.FromDatetime(_now())
        yield firestore_pb2.BatchGetDocumentsResponse(read_time=read_ts)

    # ------------------------------------------------------------------
    # ListDocuments
    # ------------------------------------------------------------------

    async def ListDocuments(self, request: Any, context: Any) -> Any:
        try:
            project, database, parent_path = _parse_parent_for_list(request.parent)
            collection_id = request.collection_id
            page_size = request.page_size or 0  # 0 = unlimited
            page_token = request.page_token or ""

            docs: list[DocumentRecord] = []
            async for rec in self._storage.iter_collection(
                project,
                database,
                collection_id,
                all_descendants=False,
                parent_path=parent_path,
            ):
                docs.append(rec)

            # Sort by path for stable ordering
            docs.sort(key=lambda r: r.path)

            # Apply page_token (resume after the path stored in the token)
            if page_token:
                try:
                    start_idx = next(i + 1 for i, r in enumerate(docs) if r.path == page_token)
                    docs = docs[start_idx:]
                except StopIteration:
                    docs = []

            next_page_token = ""
            if page_size and len(docs) > page_size:
                docs = docs[:page_size]
                next_page_token = docs[-1].path

            return firestore_pb2.ListDocumentsResponse(
                documents=[_doc_to_proto(r) for r in docs],
                next_page_token=next_page_token,
            )
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            raise

    # ------------------------------------------------------------------
    # ListCollectionIds
    # ------------------------------------------------------------------

    async def ListCollectionIds(self, request: Any, context: Any) -> Any:
        try:
            project, database, parent_path = _parse_parent_for_list(request.parent)
            page_size = request.page_size or 0
            page_token = request.page_token or ""

            # Collect all docs under this parent, then extract collection IDs
            # from the path segment immediately following the parent_path prefix.
            collection_ids: set[str] = set()

            bucket = await _iter_all_docs(self._storage, project, database)
            prefix = f"{parent_path}/" if parent_path else ""
            for path in bucket:
                if not path.startswith(prefix):
                    continue
                remainder = path[len(prefix) :]
                segments = remainder.split("/")
                if len(segments) >= 2:  # at least coll/doc
                    collection_ids.add(segments[0])

            sorted_ids = sorted(collection_ids)

            # Apply page_token
            if page_token:
                try:
                    start_idx = sorted_ids.index(page_token) + 1
                    sorted_ids = sorted_ids[start_idx:]
                except ValueError:
                    sorted_ids = []

            next_page_token = ""
            if page_size and len(sorted_ids) > page_size:
                sorted_ids = sorted_ids[:page_size]
                next_page_token = sorted_ids[-1]

            return firestore_pb2.ListCollectionIdsResponse(
                collection_ids=sorted_ids,
                next_page_token=next_page_token,
            )
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            raise

    # ------------------------------------------------------------------
    # Unimplemented stubs — wired in Task 8/11/12/13
    # ------------------------------------------------------------------

    async def Commit(self, request: Any, context: Any) -> Any:
        await errors.abort_with(context, errors.Unimplemented("Commit"))

    async def BatchWrite(self, request: Any, context: Any) -> Any:
        await errors.abort_with(context, errors.Unimplemented("BatchWrite"))

    async def RunQuery(self, request: Any, context: Any) -> AsyncIterator[Any]:
        await errors.abort_with(context, errors.Unimplemented("RunQuery"))
        return
        yield  # make this an async generator

    async def RunAggregationQuery(self, request: Any, context: Any) -> AsyncIterator[Any]:
        await errors.abort_with(context, errors.Unimplemented("RunAggregationQuery"))
        return
        yield

    async def BeginTransaction(self, request: Any, context: Any) -> Any:
        await errors.abort_with(context, errors.Unimplemented("BeginTransaction"))

    async def Rollback(self, request: Any, context: Any) -> Any:
        await errors.abort_with(context, errors.Unimplemented("Rollback"))

    async def Listen(self, request_iterator: Any, context: Any) -> AsyncIterator[Any]:
        await errors.abort_with(context, errors.Unimplemented("Listen"))
        return
        yield

    async def PartitionQuery(self, request: Any, context: Any) -> AsyncIterator[Any]:
        await errors.abort_with(context, errors.Unimplemented("PartitionQuery"))
        return
        yield

    async def Write(self, request_iterator: Any, context: Any) -> AsyncIterator[Any]:
        await errors.abort_with(context, errors.Unimplemented("Write"))
        return
        yield


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _set_nested(target: dict[str, Any], parts: list[str], source: dict[str, Any]) -> None:
    """Set a nested field in target using a dotted path from source."""
    # Navigate source to find the value
    src_val: Any = source
    for part in parts:
        if not isinstance(src_val, dict) or part not in src_val:
            # Source doesn't have this nested path → delete from target if present
            _delete_nested(target, parts)
            return
        src_val = src_val[part]

    # Navigate/create target path
    d = target
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = src_val


def _delete_nested(target: dict[str, Any], parts: list[str]) -> None:
    """Remove a nested key from target using dotted path parts."""
    d = target
    for part in parts[:-1]:
        if not isinstance(d, dict) or part not in d:
            return
        d = d[part]
    if isinstance(d, dict):
        d.pop(parts[-1], None)


async def _iter_all_docs(storage: FirestoreStorage, project: str, database: str) -> list[str]:
    """Return all document paths for (project, database).

    InMemoryStorage exposes _documents directly; we use a broad iter_collection
    over a sentinel that cannot match, then fall back to the internal dict.
    This avoids coupling to implementation details for the Protocol; however,
    InMemoryStorage is our only concrete impl for now.
    """
    # Access the internal store directly — acceptable for an emulator
    internal = getattr(storage, "_documents", None)
    if internal is not None:
        bucket = internal.get((project, database), {})
        return list(bucket.keys())
    # Protocol fallback: not reachable with current impls
    return []  # pragma: no cover


# ---------------------------------------------------------------------------
# FirestoreAdminServicer — Task 13 fills in the RPC bodies
# ---------------------------------------------------------------------------


class FirestoreAdminServicer(firestore_admin_pb2_grpc.FirestoreAdminServicer):  # type: ignore[misc, name-defined]
    def __init__(self, storage: FirestoreStorage) -> None:
        self._storage = storage
