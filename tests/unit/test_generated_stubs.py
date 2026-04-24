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
