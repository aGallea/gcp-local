from google.api import annotations_pb2 as _annotations_pb2
from google.api import client_pb2 as _client_pb2
from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.cloud.secretmanager.v1 import resources_pb2 as _resources_pb2
from google.iam.v1 import iam_policy_pb2 as _iam_policy_pb2
from google.iam.v1 import policy_pb2 as _policy_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import field_mask_pb2 as _field_mask_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ListSecretsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ...) -> None: ...

class ListSecretsResponse(_message.Message):
    __slots__ = ("secrets", "next_page_token", "total_size")
    SECRETS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    secrets: _containers.RepeatedCompositeFieldContainer[_resources_pb2.Secret]
    next_page_token: str
    total_size: int
    def __init__(self, secrets: _Optional[_Iterable[_Union[_resources_pb2.Secret, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class CreateSecretRequest(_message.Message):
    __slots__ = ("parent", "secret_id", "secret")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    SECRET_ID_FIELD_NUMBER: _ClassVar[int]
    SECRET_FIELD_NUMBER: _ClassVar[int]
    parent: str
    secret_id: str
    secret: _resources_pb2.Secret
    def __init__(self, parent: _Optional[str] = ..., secret_id: _Optional[str] = ..., secret: _Optional[_Union[_resources_pb2.Secret, _Mapping]] = ...) -> None: ...

class AddSecretVersionRequest(_message.Message):
    __slots__ = ("parent", "payload")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    parent: str
    payload: _resources_pb2.SecretPayload
    def __init__(self, parent: _Optional[str] = ..., payload: _Optional[_Union[_resources_pb2.SecretPayload, _Mapping]] = ...) -> None: ...

class GetSecretRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListSecretVersionsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ...) -> None: ...

class ListSecretVersionsResponse(_message.Message):
    __slots__ = ("versions", "next_page_token", "total_size")
    VERSIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    versions: _containers.RepeatedCompositeFieldContainer[_resources_pb2.SecretVersion]
    next_page_token: str
    total_size: int
    def __init__(self, versions: _Optional[_Iterable[_Union[_resources_pb2.SecretVersion, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class GetSecretVersionRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class UpdateSecretRequest(_message.Message):
    __slots__ = ("secret", "update_mask")
    SECRET_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    secret: _resources_pb2.Secret
    update_mask: _field_mask_pb2.FieldMask
    def __init__(self, secret: _Optional[_Union[_resources_pb2.Secret, _Mapping]] = ..., update_mask: _Optional[_Union[_field_mask_pb2.FieldMask, _Mapping]] = ...) -> None: ...

class AccessSecretVersionRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class AccessSecretVersionResponse(_message.Message):
    __slots__ = ("name", "payload")
    NAME_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    name: str
    payload: _resources_pb2.SecretPayload
    def __init__(self, name: _Optional[str] = ..., payload: _Optional[_Union[_resources_pb2.SecretPayload, _Mapping]] = ...) -> None: ...

class DeleteSecretRequest(_message.Message):
    __slots__ = ("name", "etag")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    name: str
    etag: str
    def __init__(self, name: _Optional[str] = ..., etag: _Optional[str] = ...) -> None: ...

class DisableSecretVersionRequest(_message.Message):
    __slots__ = ("name", "etag")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    name: str
    etag: str
    def __init__(self, name: _Optional[str] = ..., etag: _Optional[str] = ...) -> None: ...

class EnableSecretVersionRequest(_message.Message):
    __slots__ = ("name", "etag")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    name: str
    etag: str
    def __init__(self, name: _Optional[str] = ..., etag: _Optional[str] = ...) -> None: ...

class DestroySecretVersionRequest(_message.Message):
    __slots__ = ("name", "etag")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    name: str
    etag: str
    def __init__(self, name: _Optional[str] = ..., etag: _Optional[str] = ...) -> None: ...
