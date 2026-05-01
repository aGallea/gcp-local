"""Firestore exception types and gRPC error mapping."""

from dataclasses import dataclass

import grpc


class FirestoreError(Exception):
    """Base for all Firestore service exceptions."""


class DocumentNotFound(FirestoreError):
    pass


# Reserved per spec §8 error table; no current call site raises it because
# collections come into existence implicitly with their first document.
class CollectionNotFound(FirestoreError):
    pass


class DatabaseNotFound(FirestoreError):
    pass


class DocumentAlreadyExists(FirestoreError):
    pass


class InvalidName(FirestoreError):
    pass


class InvalidArgument(FirestoreError):
    pass


class FailedPrecondition(FirestoreError):
    pass


class TransactionAborted(FirestoreError):
    pass


class TransactionNotFound(FirestoreError):
    pass


class Unimplemented(FirestoreError):
    pass


@dataclass
class _GrpcError:
    """Lightweight grpc.RpcError stand-in for use in tests + handler return."""

    _code: grpc.StatusCode
    _details: str

    def code(self) -> grpc.StatusCode:
        return self._code

    def details(self) -> str:
        return self._details


_NOT_FOUND = (DocumentNotFound, CollectionNotFound, DatabaseNotFound)
_INVALID = (InvalidName, InvalidArgument, TransactionNotFound)


def grpc_error_for(exc: Exception) -> _GrpcError:
    if isinstance(exc, _NOT_FOUND):
        return _GrpcError(grpc.StatusCode.NOT_FOUND, str(exc))
    if isinstance(exc, DocumentAlreadyExists):
        return _GrpcError(grpc.StatusCode.ALREADY_EXISTS, str(exc))
    if isinstance(exc, _INVALID):
        return _GrpcError(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    if isinstance(exc, FailedPrecondition):
        return _GrpcError(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
    if isinstance(exc, TransactionAborted):
        return _GrpcError(grpc.StatusCode.ABORTED, str(exc))
    if isinstance(exc, Unimplemented):
        return _GrpcError(grpc.StatusCode.UNIMPLEMENTED, str(exc))
    return _GrpcError(grpc.StatusCode.INTERNAL, "internal error")


async def abort_with(context: grpc.ServicerContext, exc: Exception) -> None:
    """Convert a Firestore exception into a grpc.aio context.abort."""
    err = grpc_error_for(exc)
    await context.abort(err.code(), err.details())
