"""Transaction state machine for the Firestore emulator.

Implements optimistic concurrency control (OCC):
  - BeginTransaction snapshots the current database version.
  - Reads during the transaction are tracked in a read_set.
  - On commit, each path in the read_set is re-examined; if any document has a
    version greater than the snapshot version it means the document changed
    since the transaction started, and the transaction is aborted.
  - Read-only transactions cannot buffer writes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from gcp_local.services.firestore import errors
from gcp_local.services.firestore.errors import (
    InvalidArgument,
    TransactionAborted,
    TransactionNotFound,
)
from gcp_local.services.firestore.models import TransactionRecord

if TYPE_CHECKING:
    from gcp_local.services.firestore.storage import FirestoreStorage

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transaction lifecycle helpers
# ---------------------------------------------------------------------------


def _mint_txn_id() -> str:
    return secrets.token_hex(8)


async def begin_transaction(
    storage: FirestoreStorage,
    project: str,
    database: str,
    *,
    read_only: bool = False,
    read_time: datetime | None = None,
) -> TransactionRecord:
    """Mint a new transaction and persist it into storage.

    Returns the newly created TransactionRecord.
    """
    txn_id = _mint_txn_id()
    snapshot_version = await storage.current_version(project, database)
    txn = TransactionRecord(
        txn_id=txn_id,
        project=project,
        database=database,
        snapshot_version=snapshot_version,
        read_only=read_only,
        started_at=datetime.now(tz=UTC),
        read_set=set(),
        read_time=read_time,
    )
    await storage.put_transaction(txn)
    return txn


async def record_read(
    storage: FirestoreStorage,
    project: str,
    database: str,
    txn_id: str,
    path: str,
) -> None:
    """Add *path* to the transaction's read_set.

    Raises TransactionNotFound if the transaction is missing or expired.
    """
    txn = await storage.get_transaction(project, database, txn_id)
    if txn is None:
        raise TransactionNotFound(f"transaction {txn_id!r} not found or expired")
    txn.read_set.add(path)
    await storage.put_transaction(txn)


async def commit_transaction(
    storage: FirestoreStorage,
    project: str,
    database: str,
    txn_id: str,
    has_writes: bool = False,
) -> TransactionRecord:
    """Validate the read_set for conflicts; return the txn on success.

    Raises:
        TransactionNotFound  — txn does not exist.
        InvalidArgument      — read-only txn with writes buffered.
        TransactionAborted   — a read doc was modified since snapshot.

    The caller is responsible for applying writes and calling drop_transaction
    after the writes are persisted.
    """
    txn = await storage.get_transaction(project, database, txn_id)
    if txn is None:
        raise TransactionNotFound(f"transaction {txn_id!r} not found or expired")

    if txn.read_only and has_writes:
        raise InvalidArgument("read-only transaction cannot include writes")

    # Check each path in the read_set for conflicts.
    # DocumentNotFound means the doc didn't exist at read-time and still
    # doesn't (or was deleted); that's not a conflict in Firestore OCC.
    for path in txn.read_set:
        try:
            doc = await storage.get_document(project, database, path)
        except errors.DocumentNotFound:
            # Not a conflict — doc was absent when read and is still absent.
            continue
        if doc.version > txn.snapshot_version:
            raise TransactionAborted(
                f"document {path!r} was modified after the transaction snapshot "
                f"(doc version {doc.version}, snapshot {txn.snapshot_version})"
            )

    return txn


async def rollback(
    storage: FirestoreStorage,
    project: str,
    database: str,
    txn_id: str,
) -> None:
    """Drop a transaction, ignoring the case where it no longer exists."""
    await storage.drop_transaction(project, database, txn_id)


# ---------------------------------------------------------------------------
# TTL Sweeper
# ---------------------------------------------------------------------------


class TransactionTtlSweeper:
    """Background task that evicts transactions that have exceeded their TTL.

    Lifecycle mirrors pubsub's RedeliverySweeper: call ``await start()`` once,
    ``await stop()`` to cancel.
    """

    def __init__(
        self,
        storage: FirestoreStorage,
        *,
        interval_s: float = 30.0,
        ttl: timedelta = timedelta(seconds=60),
    ) -> None:
        self._storage = storage
        self._interval = interval_s
        self._ttl = ttl
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="firestore-txn-ttl-sweeper")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.now(tz=UTC)
                cutoff = now - self._ttl
                for txn in await self._storage.all_transactions():
                    if txn.started_at < cutoff:
                        log.debug(
                            "sweeping stale transaction %s (started %s)",
                            txn.txn_id,
                            txn.started_at.isoformat(),
                        )
                        await self._storage.drop_transaction(txn.project, txn.database, txn.txn_id)
            except Exception:
                log.exception("firestore txn TTL sweeper error (continuing)")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue
