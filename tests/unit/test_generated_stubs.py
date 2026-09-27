def test_servicer_base_class_importable():
    from gcp_local.generated.google.cloud.secretmanager.v1 import service_pb2_grpc

    assert hasattr(service_pb2_grpc, "SecretManagerServiceServicer")
    assert hasattr(service_pb2_grpc, "add_SecretManagerServiceServicer_to_server")


def test_message_types_importable():
    from gcp_local.generated.google.cloud.secretmanager.v1 import (
        resources_pb2,
        service_pb2,
    )

    assert hasattr(resources_pb2, "Secret")
    assert hasattr(resources_pb2, "SecretVersion")
    assert hasattr(service_pb2, "CreateSecretRequest")
    assert hasattr(service_pb2, "AddSecretVersionRequest")
    assert hasattr(service_pb2, "AccessSecretVersionRequest")


def test_servicer_has_expected_methods():
    from gcp_local.generated.google.cloud.secretmanager.v1 import service_pb2_grpc

    servicer_cls = service_pb2_grpc.SecretManagerServiceServicer
    for m in (
        "CreateSecret",
        "GetSecret",
        "ListSecrets",
        "UpdateSecret",
        "DeleteSecret",
        "AddSecretVersion",
        "GetSecretVersion",
        "ListSecretVersions",
        "AccessSecretVersion",
        "EnableSecretVersion",
        "DisableSecretVersion",
        "DestroySecretVersion",
    ):
        assert hasattr(servicer_cls, m), f"missing method: {m}"


def test_storage_v2_servicer_exposes_the_object_rpcs():
    from gcp_local.generated.google.storage.v2 import storage_pb2, storage_pb2_grpc

    servicer_cls = storage_pb2_grpc.StorageServicer
    for m in (
        "ListObjects",
        "GetObject",
        "ReadObject",
        "DeleteObject",
        "ComposeObject",
        "WriteObject",
    ):
        assert hasattr(servicer_cls, m), f"missing method: {m}"
    assert hasattr(storage_pb2_grpc, "add_StorageServicer_to_server")
    assert hasattr(storage_pb2, "WriteObjectRequest")
