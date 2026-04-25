import grpc

from gcp_local.core.errors import GrpcError


def test_grpc_error_dataclass_fields():
    err = GrpcError(code=grpc.StatusCode.NOT_FOUND, message="nope")
    assert err.code == grpc.StatusCode.NOT_FOUND
    assert err.message == "nope"
    assert err.reason is None


def test_grpc_error_with_reason():
    err = GrpcError(
        code=grpc.StatusCode.ALREADY_EXISTS,
        message="already there",
        reason="ALREADY_EXISTS",
    )
    assert err.reason == "ALREADY_EXISTS"


def test_grpc_error_str_includes_code_and_message():
    err = GrpcError(code=grpc.StatusCode.INVALID_ARGUMENT, message="bad")
    s = str(err)
    assert "INVALID_ARGUMENT" in s
    assert "bad" in s
