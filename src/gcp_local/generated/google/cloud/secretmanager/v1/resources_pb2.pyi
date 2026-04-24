import datetime

from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Secret(_message.Message):
    __slots__ = ("name", "replication", "create_time", "labels", "topics", "expire_time", "ttl", "etag", "rotation", "version_aliases", "annotations", "version_destroy_ttl", "customer_managed_encryption", "tags")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class VersionAliasesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    class AnnotationsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class TagsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    REPLICATION_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    TOPICS_FIELD_NUMBER: _ClassVar[int]
    EXPIRE_TIME_FIELD_NUMBER: _ClassVar[int]
    TTL_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    ROTATION_FIELD_NUMBER: _ClassVar[int]
    VERSION_ALIASES_FIELD_NUMBER: _ClassVar[int]
    ANNOTATIONS_FIELD_NUMBER: _ClassVar[int]
    VERSION_DESTROY_TTL_FIELD_NUMBER: _ClassVar[int]
    CUSTOMER_MANAGED_ENCRYPTION_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    replication: Replication
    create_time: _timestamp_pb2.Timestamp
    labels: _containers.ScalarMap[str, str]
    topics: _containers.RepeatedCompositeFieldContainer[Topic]
    expire_time: _timestamp_pb2.Timestamp
    ttl: _duration_pb2.Duration
    etag: str
    rotation: Rotation
    version_aliases: _containers.ScalarMap[str, int]
    annotations: _containers.ScalarMap[str, str]
    version_destroy_ttl: _duration_pb2.Duration
    customer_managed_encryption: CustomerManagedEncryption
    tags: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., replication: _Optional[_Union[Replication, _Mapping]] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., labels: _Optional[_Mapping[str, str]] = ..., topics: _Optional[_Iterable[_Union[Topic, _Mapping]]] = ..., expire_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., ttl: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., etag: _Optional[str] = ..., rotation: _Optional[_Union[Rotation, _Mapping]] = ..., version_aliases: _Optional[_Mapping[str, int]] = ..., annotations: _Optional[_Mapping[str, str]] = ..., version_destroy_ttl: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., customer_managed_encryption: _Optional[_Union[CustomerManagedEncryption, _Mapping]] = ..., tags: _Optional[_Mapping[str, str]] = ...) -> None: ...

class SecretVersion(_message.Message):
    __slots__ = ("name", "create_time", "destroy_time", "state", "replication_status", "etag", "client_specified_payload_checksum", "scheduled_destroy_time", "customer_managed_encryption")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[SecretVersion.State]
        ENABLED: _ClassVar[SecretVersion.State]
        DISABLED: _ClassVar[SecretVersion.State]
        DESTROYED: _ClassVar[SecretVersion.State]
    STATE_UNSPECIFIED: SecretVersion.State
    ENABLED: SecretVersion.State
    DISABLED: SecretVersion.State
    DESTROYED: SecretVersion.State
    NAME_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    DESTROY_TIME_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    REPLICATION_STATUS_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    CLIENT_SPECIFIED_PAYLOAD_CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    SCHEDULED_DESTROY_TIME_FIELD_NUMBER: _ClassVar[int]
    CUSTOMER_MANAGED_ENCRYPTION_FIELD_NUMBER: _ClassVar[int]
    name: str
    create_time: _timestamp_pb2.Timestamp
    destroy_time: _timestamp_pb2.Timestamp
    state: SecretVersion.State
    replication_status: ReplicationStatus
    etag: str
    client_specified_payload_checksum: bool
    scheduled_destroy_time: _timestamp_pb2.Timestamp
    customer_managed_encryption: CustomerManagedEncryptionStatus
    def __init__(self, name: _Optional[str] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., destroy_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., state: _Optional[_Union[SecretVersion.State, str]] = ..., replication_status: _Optional[_Union[ReplicationStatus, _Mapping]] = ..., etag: _Optional[str] = ..., client_specified_payload_checksum: bool = ..., scheduled_destroy_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., customer_managed_encryption: _Optional[_Union[CustomerManagedEncryptionStatus, _Mapping]] = ...) -> None: ...

class Replication(_message.Message):
    __slots__ = ("automatic", "user_managed")
    class Automatic(_message.Message):
        __slots__ = ("customer_managed_encryption",)
        CUSTOMER_MANAGED_ENCRYPTION_FIELD_NUMBER: _ClassVar[int]
        customer_managed_encryption: CustomerManagedEncryption
        def __init__(self, customer_managed_encryption: _Optional[_Union[CustomerManagedEncryption, _Mapping]] = ...) -> None: ...
    class UserManaged(_message.Message):
        __slots__ = ("replicas",)
        class Replica(_message.Message):
            __slots__ = ("location", "customer_managed_encryption")
            LOCATION_FIELD_NUMBER: _ClassVar[int]
            CUSTOMER_MANAGED_ENCRYPTION_FIELD_NUMBER: _ClassVar[int]
            location: str
            customer_managed_encryption: CustomerManagedEncryption
            def __init__(self, location: _Optional[str] = ..., customer_managed_encryption: _Optional[_Union[CustomerManagedEncryption, _Mapping]] = ...) -> None: ...
        REPLICAS_FIELD_NUMBER: _ClassVar[int]
        replicas: _containers.RepeatedCompositeFieldContainer[Replication.UserManaged.Replica]
        def __init__(self, replicas: _Optional[_Iterable[_Union[Replication.UserManaged.Replica, _Mapping]]] = ...) -> None: ...
    AUTOMATIC_FIELD_NUMBER: _ClassVar[int]
    USER_MANAGED_FIELD_NUMBER: _ClassVar[int]
    automatic: Replication.Automatic
    user_managed: Replication.UserManaged
    def __init__(self, automatic: _Optional[_Union[Replication.Automatic, _Mapping]] = ..., user_managed: _Optional[_Union[Replication.UserManaged, _Mapping]] = ...) -> None: ...

class CustomerManagedEncryption(_message.Message):
    __slots__ = ("kms_key_name",)
    KMS_KEY_NAME_FIELD_NUMBER: _ClassVar[int]
    kms_key_name: str
    def __init__(self, kms_key_name: _Optional[str] = ...) -> None: ...

class ReplicationStatus(_message.Message):
    __slots__ = ("automatic", "user_managed")
    class AutomaticStatus(_message.Message):
        __slots__ = ("customer_managed_encryption",)
        CUSTOMER_MANAGED_ENCRYPTION_FIELD_NUMBER: _ClassVar[int]
        customer_managed_encryption: CustomerManagedEncryptionStatus
        def __init__(self, customer_managed_encryption: _Optional[_Union[CustomerManagedEncryptionStatus, _Mapping]] = ...) -> None: ...
    class UserManagedStatus(_message.Message):
        __slots__ = ("replicas",)
        class ReplicaStatus(_message.Message):
            __slots__ = ("location", "customer_managed_encryption")
            LOCATION_FIELD_NUMBER: _ClassVar[int]
            CUSTOMER_MANAGED_ENCRYPTION_FIELD_NUMBER: _ClassVar[int]
            location: str
            customer_managed_encryption: CustomerManagedEncryptionStatus
            def __init__(self, location: _Optional[str] = ..., customer_managed_encryption: _Optional[_Union[CustomerManagedEncryptionStatus, _Mapping]] = ...) -> None: ...
        REPLICAS_FIELD_NUMBER: _ClassVar[int]
        replicas: _containers.RepeatedCompositeFieldContainer[ReplicationStatus.UserManagedStatus.ReplicaStatus]
        def __init__(self, replicas: _Optional[_Iterable[_Union[ReplicationStatus.UserManagedStatus.ReplicaStatus, _Mapping]]] = ...) -> None: ...
    AUTOMATIC_FIELD_NUMBER: _ClassVar[int]
    USER_MANAGED_FIELD_NUMBER: _ClassVar[int]
    automatic: ReplicationStatus.AutomaticStatus
    user_managed: ReplicationStatus.UserManagedStatus
    def __init__(self, automatic: _Optional[_Union[ReplicationStatus.AutomaticStatus, _Mapping]] = ..., user_managed: _Optional[_Union[ReplicationStatus.UserManagedStatus, _Mapping]] = ...) -> None: ...

class CustomerManagedEncryptionStatus(_message.Message):
    __slots__ = ("kms_key_version_name",)
    KMS_KEY_VERSION_NAME_FIELD_NUMBER: _ClassVar[int]
    kms_key_version_name: str
    def __init__(self, kms_key_version_name: _Optional[str] = ...) -> None: ...

class Topic(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class Rotation(_message.Message):
    __slots__ = ("next_rotation_time", "rotation_period")
    NEXT_ROTATION_TIME_FIELD_NUMBER: _ClassVar[int]
    ROTATION_PERIOD_FIELD_NUMBER: _ClassVar[int]
    next_rotation_time: _timestamp_pb2.Timestamp
    rotation_period: _duration_pb2.Duration
    def __init__(self, next_rotation_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., rotation_period: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class SecretPayload(_message.Message):
    __slots__ = ("data", "data_crc32c")
    DATA_FIELD_NUMBER: _ClassVar[int]
    DATA_CRC32C_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    data_crc32c: int
    def __init__(self, data: _Optional[bytes] = ..., data_crc32c: _Optional[int] = ...) -> None: ...
