"""Firestore gRPC servicers — document CRUD + query RPCs."""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from google.protobuf import empty_pb2
from google.protobuf.timestamp_pb2 import Timestamp
from google.rpc import status_pb2

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc
from gcp_local.generated.google.firestore.v1 import (
    document_pb2,
    firestore_pb2,
    firestore_pb2_grpc,
    write_pb2,
)
from gcp_local.services.firestore import errors, names
from gcp_local.services.firestore.engine.aggregations import aggregate
from gcp_local.services.firestore.engine.query import run_query
from gcp_local.services.firestore.engine.transactions import (
    begin_transaction,
    commit_transaction,
    record_read,
    rollback,
)
from gcp_local.services.firestore.engine.transforms import apply_transform
from gcp_local.services.firestore.models import DocumentRecord, IndexRecord
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
            # exists=false precondition violated → doc already exists.
            # Real Firestore returns ALREADY_EXISTS (status 6) here, not
            # FAILED_PRECONDITION, so we raise DocumentAlreadyExists which
            # maps to ALREADY_EXISTS in grpc_error_for().
            raise errors.DocumentAlreadyExists("document already exists")
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


def _parse_run_query_parent(parent: str) -> tuple[str, str, str]:
    """Parse a RunQuery / RunAggregationQuery parent resource name.

    Accepted forms:
      projects/<p>/databases/<db>/documents           → parent_path = ""
      projects/<p>/databases/<db>/documents/<path>    → parent_path = <path>

    Returns (project, database, parent_path).
    Raises InvalidName for malformed strings.
    """
    m = re.match(r"^projects/([^/]+)/databases/([^/]+)/documents(?:/(.+))?$", parent)
    if not m:
        raise errors.InvalidName(f"invalid RunQuery parent: {parent!r}")
    return m.group(1), m.group(2), m.group(3) or ""


def _parse_parent_for_list(parent: str) -> tuple[str, str, str]:
    """Parse a ListDocuments/ListCollectionIds parent into (project, database, doc_path).

    parent is one of:
      projects/<p>/databases/<db>/documents            -> doc_path = ""
      projects/<p>/databases/<db>/documents/<path>     -> doc_path = <path>
    """
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

            # Resolve transaction context if provided
            txn_id: str | None = None
            read_time_filter: datetime | None = None
            if request.transaction:
                txn_id = request.transaction.decode("ascii")
                txn = await self._storage.get_transaction(project, database, txn_id)
                if txn is None:
                    raise errors.TransactionNotFound(f"transaction {txn_id!r} not found")
                read_time_filter = txn.read_time

            # Record the read (before actually reading — per Firestore semantics,
            # the path is in the read_set regardless of whether the doc exists).
            if txn_id is not None:
                await record_read(self._storage, project, database, txn_id, path)

            try:
                rec = await self._storage.get_document(project, database, path)
            except errors.DocumentNotFound:
                if txn_id is not None:
                    raise errors.DocumentNotFound(path) from None
                raise

            # Filter by read_time if the transaction has one (read-only snapshot).
            if read_time_filter is not None and rec.update_time > read_time_filter:
                raise errors.DocumentNotFound(path)

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
            await self._storage.snapshot(project, database)
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
            await self._storage.snapshot(project, database)
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
            await self._storage.snapshot(project, database)
            return empty_pb2.Empty()
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            raise

    # ------------------------------------------------------------------
    # BatchGetDocuments  (server-streaming)
    # ------------------------------------------------------------------

    async def BatchGetDocuments(self, request: Any, context: Any) -> AsyncIterator[Any]:
        try:
            # database field: "projects/<p>/databases/<db>"
            project, database = names.parse_database_root(request.database)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        # Resolve transaction context if provided
        txn_id: str | None = None
        read_time_filter: datetime | None = None
        if request.transaction:
            txn_id = request.transaction.decode("ascii")
            txn = await self._storage.get_transaction(project, database, txn_id)
            if txn is None:
                await errors.abort_with(
                    context, errors.TransactionNotFound(f"transaction {txn_id!r} not found")
                )
                return
            read_time_filter = txn.read_time

        names_list = list(request.documents)
        for doc_name in names_list:
            try:
                _, _, path = names.parse_document_path(doc_name)

                # Record every candidate path in the read_set
                if txn_id is not None:
                    try:
                        await record_read(self._storage, project, database, txn_id, path)
                    except errors.TransactionNotFound as exc:
                        await errors.abort_with(context, exc)
                        return

                try:
                    rec = await self._storage.get_document(project, database, path)
                    # Filter by read_time snapshot
                    if read_time_filter is not None and rec.update_time > read_time_filter:
                        yield firestore_pb2.BatchGetDocumentsResponse(missing=doc_name)
                    else:
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
    # Commit (atomic multi-write)  — Task 8
    # ------------------------------------------------------------------

    async def Commit(self, request: Any, context: Any) -> Any:
        try:
            project, database = names.parse_database_root(request.database)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        # Determine if this is a transactional commit.
        txn_id: str | None = None
        if request.transaction:
            txn_id = request.transaction.decode("ascii")

        commit_time = _now()
        commit_ts = Timestamp()
        commit_ts.FromDatetime(commit_time)

        lock = self._storage.lock(project, database)
        async with lock:
            # For transactional commits, validate the read-set before applying writes.
            if txn_id is not None:
                try:
                    await commit_transaction(
                        self._storage,
                        project,
                        database,
                        txn_id,
                        has_writes=bool(request.writes),
                    )
                except errors.FirestoreError as exc:
                    await errors.abort_with(context, exc)
                    return

            # Phase 1: compute new states for all writes (no persistence yet).
            # If any write fails, the entire commit is aborted.
            pending: list[tuple[str, DocumentRecord | None, list[Any]]] = []
            try:
                for write in request.writes:
                    path, new_rec, transform_results = await _apply_write(
                        self._storage, project, database, write, commit_time
                    )
                    pending.append((path, new_rec, transform_results))
            except errors.FirestoreError as exc:
                await errors.abort_with(context, exc)
                return

            # Phase 2: persist all computed states.
            write_results: list[write_pb2.WriteResult] = []
            for (path, new_rec, transform_results), _write in zip(
                pending, request.writes, strict=True
            ):
                if new_rec is not None:
                    await self._storage.put_document(new_rec)
                    wr = write_pb2.WriteResult(update_time=commit_ts)
                    if transform_results:
                        wr.transform_results.extend(transform_results)
                    write_results.append(wr)
                    # Use update_time==create_time as proxy for "newly created".
                    op_label = "create" if new_rec.create_time == new_rec.update_time else "update"
                else:
                    # delete
                    await self._storage.delete_document(project, database, path)
                    write_results.append(write_pb2.WriteResult())
                    op_label = "delete"

                if self._state_hub is not None:
                    await self._state_hub.publish(
                        "firestore.document.written",
                        {
                            "project": project,
                            "database": database,
                            "path": path,
                            "operation": op_label,
                            "update_time": commit_time.isoformat(),
                        },
                    )

            # Drop the transaction after writes are persisted.
            if txn_id is not None:
                await self._storage.drop_transaction(project, database, txn_id)

        await self._storage.snapshot(project, database)
        return firestore_pb2.CommitResponse(
            write_results=write_results,
            commit_time=commit_ts,
        )

    # ------------------------------------------------------------------
    # BatchWrite (independent per-write)  — Task 8
    # ------------------------------------------------------------------

    async def BatchWrite(self, request: Any, context: Any) -> Any:
        try:
            project, database = names.parse_database_root(request.database)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        write_results: list[write_pb2.WriteResult] = []
        statuses: list[status_pb2.Status] = []

        commit_time = _now()
        commit_ts = Timestamp()
        commit_ts.FromDatetime(commit_time)

        for write in request.writes:
            try:
                path, new_rec, transform_results = await _apply_write(
                    self._storage, project, database, write, commit_time
                )
            except errors.FirestoreError as exc:
                grpc_err = errors.grpc_error_for(exc)
                write_results.append(write_pb2.WriteResult())
                statuses.append(
                    status_pb2.Status(
                        code=grpc_err.code().value[0],
                        message=grpc_err.details(),
                    )
                )
                continue

            # Persist this individual write
            if new_rec is not None:
                await self._storage.put_document(new_rec)
                wr = write_pb2.WriteResult(update_time=commit_ts)
                if transform_results:
                    wr.transform_results.extend(transform_results)
                write_results.append(wr)
                op_label = "create" if new_rec.create_time == new_rec.update_time else "update"
            else:
                await self._storage.delete_document(project, database, path)
                write_results.append(write_pb2.WriteResult())
                op_label = "delete"

            statuses.append(status_pb2.Status(code=0))

            if self._state_hub is not None:
                await self._state_hub.publish(
                    "firestore.document.written",
                    {
                        "project": project,
                        "database": database,
                        "path": path,
                        "operation": op_label,
                        "update_time": commit_time.isoformat(),
                    },
                )

        await self._storage.snapshot(project, database)
        return firestore_pb2.BatchWriteResponse(
            write_results=write_results,
            status=statuses,
        )

    async def RunQuery(self, request: Any, context: Any) -> AsyncIterator[Any]:
        try:
            project, database, parent_path = _parse_run_query_parent(request.parent)

            # Resolve transaction context if provided
            txn_id: str | None = None
            read_time_filter: datetime | None = None
            if request.transaction:
                txn_id = request.transaction.decode("ascii")
                txn = await self._storage.get_transaction(project, database, txn_id)
                if txn is None:
                    await errors.abort_with(
                        context,
                        errors.TransactionNotFound(f"transaction {txn_id!r} not found"),
                    )
                    return
                read_time_filter = txn.read_time

            # Run the query to obtain candidates; the read_set includes ALL
            # candidates (scanned set), not just those matching the filter.
            # To achieve this, we need to track the full scanned set separately.
            # run_query returns only matching records; for the read_set we record
            # ALL docs in the collection before filtering.
            # We implement this by collecting all docs via iter_collection and
            # tracking them, then running the standard query for matching results.
            if txn_id is not None:
                # Collect all candidate paths (the full scanned set per Firestore
                # semantics) and register them into the read_set.
                # proto-plus wraps "from" → "from_"; our generated pb2 uses "from".
                from_selectors = getattr(request.structured_query, "from_", None) or getattr(
                    request.structured_query, "from", []
                )
                if from_selectors:
                    selector = from_selectors[0]
                    async for candidate in self._storage.iter_collection(
                        project,
                        database,
                        selector.collection_id,
                        all_descendants=selector.all_descendants,
                        parent_path=parent_path,
                    ):
                        try:
                            await record_read(
                                self._storage, project, database, txn_id, candidate.path
                            )
                        except errors.TransactionNotFound as exc:
                            await errors.abort_with(context, exc)
                            return

            records = await run_query(
                self._storage, project, database, request.structured_query, parent_path
            )

            for rec in records:
                # Filter by read_time snapshot if applicable
                if read_time_filter is not None and rec.update_time > read_time_filter:
                    continue
                yield firestore_pb2.RunQueryResponse(document=_doc_to_proto(rec))

            # Final empty response with read_time signals end-of-stream.
            end = firestore_pb2.RunQueryResponse()
            end.read_time.FromDatetime(_now())
            yield end
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)

    async def RunAggregationQuery(self, request: Any, context: Any) -> AsyncIterator[Any]:
        try:
            project, database, parent_path = _parse_run_query_parent(request.parent)

            # Resolve transaction context if provided
            txn_id: str | None = None
            read_time_filter: datetime | None = None
            if request.transaction:
                txn_id = request.transaction.decode("ascii")
                txn = await self._storage.get_transaction(project, database, txn_id)
                if txn is None:
                    await errors.abort_with(
                        context,
                        errors.TransactionNotFound(f"transaction {txn_id!r} not found"),
                    )
                    return
                read_time_filter = txn.read_time

            sq = request.structured_aggregation_query.structured_query

            # Track full scanned set in the read_set (Firestore semantics).
            if txn_id is not None:
                # getattr("from") for raw pb2; from_ for proto-plus wrapped
                from_selectors = list(getattr(sq, "from", None) or sq.from_)
                if from_selectors:
                    selector = from_selectors[0]
                    async for candidate in self._storage.iter_collection(
                        project,
                        database,
                        selector.collection_id,
                        all_descendants=selector.all_descendants,
                        parent_path=parent_path,
                    ):
                        try:
                            await record_read(
                                self._storage, project, database, txn_id, candidate.path
                            )
                        except errors.TransactionNotFound as exc:
                            await errors.abort_with(context, exc)
                            return

            records = await run_query(self._storage, project, database, sq, parent_path)

            # Filter by read_time snapshot if applicable
            if read_time_filter is not None:
                records = [r for r in records if r.update_time <= read_time_filter]

            result = aggregate(records, list(request.structured_aggregation_query.aggregations))
            response = firestore_pb2.RunAggregationQueryResponse()
            for alias, value in result.items():
                response.result.aggregate_fields[alias].CopyFrom(to_proto(value))
            response.read_time.FromDatetime(_now())
            yield response
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)

    async def BeginTransaction(self, request: Any, context: Any) -> Any:
        try:
            project, database = names.parse_database_root(request.database)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        # Parse options — default is read-write.
        read_only = False
        read_time: datetime | None = None
        which_options = request.options.WhichOneof("mode") if request.HasField("options") else None
        if which_options == "read_only":
            read_only = True
            ro = request.options.read_only
            if ro.HasField("read_time"):
                read_time = ro.read_time.ToDatetime().replace(tzinfo=UTC)

        try:
            txn = await begin_transaction(
                self._storage,
                project,
                database,
                read_only=read_only,
                read_time=read_time,
            )
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        return firestore_pb2.BeginTransactionResponse(transaction=txn.txn_id.encode("ascii"))

    async def Rollback(self, request: Any, context: Any) -> Any:
        try:
            project, database = names.parse_database_root(request.database)
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        txn_id = request.transaction.decode("ascii")
        await rollback(self._storage, project, database, txn_id)
        return empty_pb2.Empty()

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


async def _apply_write(
    storage: FirestoreStorage,
    project: str,
    database: str,
    write: Any,
    commit_time: datetime,
) -> tuple[str, DocumentRecord | None, list[Any]]:
    """Compute the new document state for a single Write without persisting.

    Returns ``(path, new_record_or_None_for_delete, transform_results)``.
    Raises a FirestoreError on any validation / precondition failure.
    """
    which = write.WhichOneof("operation")
    if which == "update_pipeline":
        raise errors.Unimplemented("update_pipeline writes")

    # ------------------------------------------------------------------
    # Resolve existing document (needed by all branches)
    # ------------------------------------------------------------------
    if which == "update":
        doc_name = write.update.name
    elif which == "delete":
        doc_name = write.delete
    elif which == "transform":
        doc_name = write.transform.document
    else:
        raise errors.Unimplemented(f"unknown write operation: {which}")

    _, _, path = names.parse_document_path(doc_name)

    existing: DocumentRecord | None
    try:
        existing = await storage.get_document(project, database, path)
    except errors.DocumentNotFound:
        existing = None

    # Check precondition before applying the write.
    if write.HasField("current_document"):
        _check_precondition(existing, write.current_document)

    # ------------------------------------------------------------------
    # delete branch
    # ------------------------------------------------------------------
    if which == "delete":
        return path, None, []

    # ------------------------------------------------------------------
    # update branch
    # ------------------------------------------------------------------
    if which == "update":
        mask = write.update_mask
        if mask and list(mask.field_paths):
            merged: dict[str, Any] = dict(existing.fields) if existing else {}
            incoming = _fields_from_proto(write.update)
            for field_path in mask.field_paths:
                parts = field_path.split(".")
                if len(parts) == 1:
                    field_name = parts[0]
                    if field_name in incoming:
                        merged[field_name] = incoming[field_name]
                    else:
                        merged.pop(field_name, None)
                else:
                    _set_nested(merged, parts, incoming)
            new_fields: dict[str, Any] = merged
        else:
            new_fields = _fields_from_proto(write.update)

        create_time = existing.create_time if existing else commit_time
        version = await storage.next_version(project, database)

        # Apply update_transforms, accumulating result values.
        transform_results: list[Any] = []
        for ft in write.update_transforms:
            new_fields, result_val = apply_transform(new_fields, ft, commit_time)
            transform_results.append(to_proto(result_val))

        rec = DocumentRecord(
            project=project,
            database=database,
            path=path,
            fields=new_fields,
            create_time=create_time,
            update_time=commit_time,
            version=version,
        )
        return path, rec, transform_results

    # ------------------------------------------------------------------
    # standalone transform branch (used in transactions; rare from clients)
    # TODO: Task 12 — full transactional transform support.
    # ------------------------------------------------------------------
    if which == "transform":
        if existing is None:
            raise errors.InvalidArgument("standalone transform requires document to exist")
        new_fields = dict(existing.fields)
        transform_results_t: list[Any] = []
        for ft in write.transform.field_transforms:
            new_fields, result_val = apply_transform(new_fields, ft, commit_time)
            transform_results_t.append(to_proto(result_val))
        version = await storage.next_version(project, database)
        rec = DocumentRecord(
            project=project,
            database=database,
            path=path,
            fields=new_fields,
            create_time=existing.create_time,
            update_time=commit_time,
            version=version,
        )
        return path, rec, transform_results_t

    raise errors.Unimplemented(f"unhandled write operation: {which}")  # pragma: no cover


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
# FirestoreAdminServicer — Task 13: index accept-and-ignore + RPC stubs
# ---------------------------------------------------------------------------

_BASE62 = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_INDEX_ID_LEN = 16
_DEFAULT_PAGE_SIZE = 100

# Regex for collectionGroups parent:
#   projects/<p>/databases/<db>/collectionGroups/<g>
_COLLECTION_GROUP_RE = re.compile(r"^(projects/[^/]+/databases/[^/]+)/collectionGroups/([^/]+)$")


def _mint_index_id() -> str:
    return "".join(secrets.choice(_BASE62) for _ in range(_INDEX_ID_LEN))


def _parse_collection_group_parent(parent: str) -> tuple[str, str, str]:
    """Return (project, database, collection_group) from a collectionGroups parent.

    Raises ValueError for malformed strings.
    """
    m = _COLLECTION_GROUP_RE.match(parent)
    if not m:
        raise ValueError(f"invalid collectionGroups parent: {parent!r}")
    db_root = m.group(1)  # "projects/<p>/databases/<db>"
    group = m.group(2)
    project, database = names.parse_database_root(db_root)
    return project, database, group


def _index_record_to_proto(rec: IndexRecord) -> Any:
    """Convert a stored IndexRecord to an index_pb2.Index proto."""
    from gcp_local.generated.google.firestore.admin.v1 import index_pb2

    state_map = {
        "READY": index_pb2.Index.READY,
        "CREATING": index_pb2.Index.CREATING,
        "NEEDS_REPAIR": index_pb2.Index.NEEDS_REPAIR,
    }
    state = state_map.get(rec.state, index_pb2.Index.READY)
    return index_pb2.Index(name=rec.name, state=state)


async def _unimplemented(rpc_name: str, context: Any) -> None:
    """Abort context with UNIMPLEMENTED for the named RPC."""
    await errors.abort_with(context, errors.Unimplemented(rpc_name))


class FirestoreAdminServicer(firestore_admin_pb2_grpc.FirestoreAdminServicer):  # type: ignore[misc, name-defined]
    def __init__(self, storage: FirestoreStorage) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # CreateIndex
    # ------------------------------------------------------------------

    async def CreateIndex(self, request: Any, context: Any) -> Any:
        from google.longrunning import operations_pb2

        from gcp_local.generated.google.firestore.admin.v1 import index_pb2

        try:
            project, database, _group = _parse_collection_group_parent(request.parent)
        except (ValueError, errors.FirestoreError) as exc:
            await errors.abort_with(context, errors.InvalidName(str(exc)))
            return

        index_id = _mint_index_id()
        index_name = f"{request.parent}/indexes/{index_id}"

        # Preserve fields supplied by the caller; store as plain dicts.
        fields_data: list[dict[str, Any]] = [
            {"field_path": f.field_path} for f in request.index.fields
        ]

        rec = IndexRecord(name=index_name, fields=fields_data, state="READY")
        await self._storage.put_index(project, database, rec)

        # Build the Index proto to embed in the Operation response.
        index_proto = index_pb2.Index(name=index_name, state=index_pb2.Index.READY)

        op_name = f"{index_name}/operations/{_mint_index_id()}"
        op = operations_pb2.Operation(name=op_name, done=True)
        op.response.Pack(index_proto)
        return op

    # ------------------------------------------------------------------
    # GetIndex
    # ------------------------------------------------------------------

    async def GetIndex(self, request: Any, context: Any) -> Any:
        # name: "projects/<p>/databases/<db>/collectionGroups/<g>/indexes/<id>"
        # Extract project + database from the name prefix.
        name = request.name
        m = re.match(r"^(projects/[^/]+/databases/[^/]+)/", name)
        if not m:
            await errors.abort_with(context, errors.InvalidName(f"invalid index name: {name!r}"))
            return
        try:
            project, database = names.parse_database_root(m.group(1))
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        rec = await self._storage.get_index(project, database, name)
        if rec is None:
            await errors.abort_with(context, errors.DocumentNotFound(f"index {name!r} not found"))
            return

        return _index_record_to_proto(rec)

    # ------------------------------------------------------------------
    # ListIndexes
    # ------------------------------------------------------------------

    async def ListIndexes(self, request: Any, context: Any) -> Any:
        from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2

        try:
            project, database, _group = _parse_collection_group_parent(request.parent)
        except (ValueError, errors.FirestoreError) as exc:
            await errors.abort_with(context, errors.InvalidName(str(exc)))
            return

        page_size: int = request.page_size or _DEFAULT_PAGE_SIZE
        page_token: str = request.page_token or ""

        all_indexes = await self._storage.list_indexes(project, database)
        # Filter to those whose name starts with this parent
        parent_prefix = f"{request.parent}/indexes/"
        all_indexes = [idx for idx in all_indexes if idx.name.startswith(parent_prefix)]
        all_indexes.sort(key=lambda r: r.name)

        # Apply page_token: resume after the name stored in the token.
        if page_token:
            try:
                start_idx = next(i + 1 for i, r in enumerate(all_indexes) if r.name == page_token)
                all_indexes = all_indexes[start_idx:]
            except StopIteration:
                all_indexes = []

        next_page_token = ""
        if page_size and len(all_indexes) > page_size:
            all_indexes = all_indexes[:page_size]
            next_page_token = all_indexes[-1].name

        return firestore_admin_pb2.ListIndexesResponse(
            indexes=[_index_record_to_proto(r) for r in all_indexes],
            next_page_token=next_page_token,
        )

    # ------------------------------------------------------------------
    # DeleteIndex
    # ------------------------------------------------------------------

    async def DeleteIndex(self, request: Any, context: Any) -> Any:
        name = request.name
        m = re.match(r"^(projects/[^/]+/databases/[^/]+)/", name)
        if not m:
            await errors.abort_with(context, errors.InvalidName(f"invalid index name: {name!r}"))
            return
        try:
            project, database = names.parse_database_root(m.group(1))
        except errors.FirestoreError as exc:
            await errors.abort_with(context, exc)
            return

        # No-op if missing, per real Firestore behaviour.
        await self._storage.delete_index(project, database, name)
        return empty_pb2.Empty()

    # ------------------------------------------------------------------
    # Unimplemented stubs
    # ------------------------------------------------------------------

    async def GetField(self, request: Any, context: Any) -> Any:
        await _unimplemented("GetField", context)

    async def UpdateField(self, request: Any, context: Any) -> Any:
        await _unimplemented("UpdateField", context)

    async def ListFields(self, request: Any, context: Any) -> Any:
        await _unimplemented("ListFields", context)

    async def ExportDocuments(self, request: Any, context: Any) -> Any:
        await _unimplemented("ExportDocuments", context)

    async def ImportDocuments(self, request: Any, context: Any) -> Any:
        await _unimplemented("ImportDocuments", context)

    async def BulkDeleteDocuments(self, request: Any, context: Any) -> Any:
        await _unimplemented("BulkDeleteDocuments", context)

    async def CreateDatabase(self, request: Any, context: Any) -> Any:
        await _unimplemented("CreateDatabase", context)

    async def GetDatabase(self, request: Any, context: Any) -> Any:
        await _unimplemented("GetDatabase", context)

    async def ListDatabases(self, request: Any, context: Any) -> Any:
        await _unimplemented("ListDatabases", context)

    async def UpdateDatabase(self, request: Any, context: Any) -> Any:
        await _unimplemented("UpdateDatabase", context)

    async def DeleteDatabase(self, request: Any, context: Any) -> Any:
        await _unimplemented("DeleteDatabase", context)

    async def CreateUserCreds(self, request: Any, context: Any) -> Any:
        await _unimplemented("CreateUserCreds", context)

    async def GetUserCreds(self, request: Any, context: Any) -> Any:
        await _unimplemented("GetUserCreds", context)

    async def ListUserCreds(self, request: Any, context: Any) -> Any:
        await _unimplemented("ListUserCreds", context)

    async def EnableUserCreds(self, request: Any, context: Any) -> Any:
        await _unimplemented("EnableUserCreds", context)

    async def DisableUserCreds(self, request: Any, context: Any) -> Any:
        await _unimplemented("DisableUserCreds", context)

    async def ResetUserPassword(self, request: Any, context: Any) -> Any:
        await _unimplemented("ResetUserPassword", context)

    async def DeleteUserCreds(self, request: Any, context: Any) -> Any:
        await _unimplemented("DeleteUserCreds", context)

    async def GetBackup(self, request: Any, context: Any) -> Any:
        await _unimplemented("GetBackup", context)

    async def ListBackups(self, request: Any, context: Any) -> Any:
        await _unimplemented("ListBackups", context)

    async def DeleteBackup(self, request: Any, context: Any) -> Any:
        await _unimplemented("DeleteBackup", context)

    async def RestoreDatabase(self, request: Any, context: Any) -> Any:
        await _unimplemented("RestoreDatabase", context)

    async def CreateBackupSchedule(self, request: Any, context: Any) -> Any:
        await _unimplemented("CreateBackupSchedule", context)

    async def GetBackupSchedule(self, request: Any, context: Any) -> Any:
        await _unimplemented("GetBackupSchedule", context)

    async def ListBackupSchedules(self, request: Any, context: Any) -> Any:
        await _unimplemented("ListBackupSchedules", context)

    async def UpdateBackupSchedule(self, request: Any, context: Any) -> Any:
        await _unimplemented("UpdateBackupSchedule", context)

    async def DeleteBackupSchedule(self, request: Any, context: Any) -> Any:
        await _unimplemented("DeleteBackupSchedule", context)

    async def CloneDatabase(self, request: Any, context: Any) -> Any:
        await _unimplemented("CloneDatabase", context)
