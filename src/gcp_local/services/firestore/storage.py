"""Firestore storage. CRUD primitives land in Task 5."""

from typing import Protocol


class FirestoreStorage(Protocol):
    async def reset(self) -> None: ...


class InMemoryStorage:
    async def reset(self) -> None:
        return None
