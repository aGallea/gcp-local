import grpc
import pytest

from gcp_local.services.firestore.errors import (
    DocumentAlreadyExists,
    DocumentNotFound,
    FailedPrecondition,
    FirestoreError,
    InvalidArgument,
    InvalidName,
    TransactionAborted,
    TransactionNotFound,
    Unimplemented,
    grpc_error_for,
)


@pytest.mark.parametrize(
    "exc, code",
    [
        (DocumentNotFound("users/alice"), grpc.StatusCode.NOT_FOUND),
        (DocumentAlreadyExists("users/alice"), grpc.StatusCode.ALREADY_EXISTS),
        (InvalidName("bad"), grpc.StatusCode.INVALID_ARGUMENT),
        (InvalidArgument("missing field"), grpc.StatusCode.INVALID_ARGUMENT),
        (FailedPrecondition("update_time mismatch"), grpc.StatusCode.FAILED_PRECONDITION),
        (TransactionAborted("read-set conflict"), grpc.StatusCode.ABORTED),
        (TransactionNotFound("txn-x"), grpc.StatusCode.INVALID_ARGUMENT),
        (Unimplemented("Listen"), grpc.StatusCode.UNIMPLEMENTED),
    ],
)
def test_grpc_error_for_known_exception(exc, code):
    err = grpc_error_for(exc)
    assert err.code() == code
    assert exc.args[0] in err.details()


def test_grpc_error_for_unknown_exception_is_internal():
    err = grpc_error_for(RuntimeError("oops"))
    assert err.code() == grpc.StatusCode.INTERNAL


def test_firestore_error_is_base_class():
    assert issubclass(DocumentNotFound, FirestoreError)
    assert issubclass(InvalidArgument, FirestoreError)
