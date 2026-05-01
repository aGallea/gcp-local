import datetime

from google.api import annotations_pb2 as _annotations_pb2
from google.api import client_pb2 as _client_pb2
from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.api import routing_pb2 as _routing_pb2
from google.firestore.admin.v1 import backup_pb2 as _backup_pb2
from google.firestore.admin.v1 import database_pb2 as _database_pb2
from google.firestore.admin.v1 import field_pb2 as _field_pb2
from google.firestore.admin.v1 import index_pb2 as _index_pb2
from google.firestore.admin.v1 import operation_pb2 as _operation_pb2
from google.firestore.admin.v1 import schedule_pb2 as _schedule_pb2
from google.firestore.admin.v1 import snapshot_pb2 as _snapshot_pb2
from google.firestore.admin.v1 import user_creds_pb2 as _user_creds_pb2
from google.longrunning import operations_pb2 as _operations_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import field_mask_pb2 as _field_mask_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ListDatabasesRequest(_message.Message):
    __slots__ = ("parent", "show_deleted")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    SHOW_DELETED_FIELD_NUMBER: _ClassVar[int]
    parent: str
    show_deleted: bool
    def __init__(self, parent: _Optional[str] = ..., show_deleted: bool = ...) -> None: ...

class CreateDatabaseRequest(_message.Message):
    __slots__ = ("parent", "database", "database_id")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    DATABASE_ID_FIELD_NUMBER: _ClassVar[int]
    parent: str
    database: _database_pb2.Database
    database_id: str
    def __init__(self, parent: _Optional[str] = ..., database: _Optional[_Union[_database_pb2.Database, _Mapping]] = ..., database_id: _Optional[str] = ...) -> None: ...

class CreateDatabaseMetadata(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListDatabasesResponse(_message.Message):
    __slots__ = ("databases", "unreachable")
    DATABASES_FIELD_NUMBER: _ClassVar[int]
    UNREACHABLE_FIELD_NUMBER: _ClassVar[int]
    databases: _containers.RepeatedCompositeFieldContainer[_database_pb2.Database]
    unreachable: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, databases: _Optional[_Iterable[_Union[_database_pb2.Database, _Mapping]]] = ..., unreachable: _Optional[_Iterable[str]] = ...) -> None: ...

class GetDatabaseRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class UpdateDatabaseRequest(_message.Message):
    __slots__ = ("database", "update_mask")
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    database: _database_pb2.Database
    update_mask: _field_mask_pb2.FieldMask
    def __init__(self, database: _Optional[_Union[_database_pb2.Database, _Mapping]] = ..., update_mask: _Optional[_Union[_field_mask_pb2.FieldMask, _Mapping]] = ...) -> None: ...

class UpdateDatabaseMetadata(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DeleteDatabaseRequest(_message.Message):
    __slots__ = ("name", "etag")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    name: str
    etag: str
    def __init__(self, name: _Optional[str] = ..., etag: _Optional[str] = ...) -> None: ...

class DeleteDatabaseMetadata(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CreateUserCredsRequest(_message.Message):
    __slots__ = ("parent", "user_creds", "user_creds_id")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    USER_CREDS_FIELD_NUMBER: _ClassVar[int]
    USER_CREDS_ID_FIELD_NUMBER: _ClassVar[int]
    parent: str
    user_creds: _user_creds_pb2.UserCreds
    user_creds_id: str
    def __init__(self, parent: _Optional[str] = ..., user_creds: _Optional[_Union[_user_creds_pb2.UserCreds, _Mapping]] = ..., user_creds_id: _Optional[str] = ...) -> None: ...

class GetUserCredsRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListUserCredsRequest(_message.Message):
    __slots__ = ("parent",)
    PARENT_FIELD_NUMBER: _ClassVar[int]
    parent: str
    def __init__(self, parent: _Optional[str] = ...) -> None: ...

class ListUserCredsResponse(_message.Message):
    __slots__ = ("user_creds",)
    USER_CREDS_FIELD_NUMBER: _ClassVar[int]
    user_creds: _containers.RepeatedCompositeFieldContainer[_user_creds_pb2.UserCreds]
    def __init__(self, user_creds: _Optional[_Iterable[_Union[_user_creds_pb2.UserCreds, _Mapping]]] = ...) -> None: ...

class EnableUserCredsRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class DisableUserCredsRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ResetUserPasswordRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class DeleteUserCredsRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class CreateBackupScheduleRequest(_message.Message):
    __slots__ = ("parent", "backup_schedule")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    BACKUP_SCHEDULE_FIELD_NUMBER: _ClassVar[int]
    parent: str
    backup_schedule: _schedule_pb2.BackupSchedule
    def __init__(self, parent: _Optional[str] = ..., backup_schedule: _Optional[_Union[_schedule_pb2.BackupSchedule, _Mapping]] = ...) -> None: ...

class GetBackupScheduleRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class UpdateBackupScheduleRequest(_message.Message):
    __slots__ = ("backup_schedule", "update_mask")
    BACKUP_SCHEDULE_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    backup_schedule: _schedule_pb2.BackupSchedule
    update_mask: _field_mask_pb2.FieldMask
    def __init__(self, backup_schedule: _Optional[_Union[_schedule_pb2.BackupSchedule, _Mapping]] = ..., update_mask: _Optional[_Union[_field_mask_pb2.FieldMask, _Mapping]] = ...) -> None: ...

class ListBackupSchedulesRequest(_message.Message):
    __slots__ = ("parent",)
    PARENT_FIELD_NUMBER: _ClassVar[int]
    parent: str
    def __init__(self, parent: _Optional[str] = ...) -> None: ...

class ListBackupSchedulesResponse(_message.Message):
    __slots__ = ("backup_schedules",)
    BACKUP_SCHEDULES_FIELD_NUMBER: _ClassVar[int]
    backup_schedules: _containers.RepeatedCompositeFieldContainer[_schedule_pb2.BackupSchedule]
    def __init__(self, backup_schedules: _Optional[_Iterable[_Union[_schedule_pb2.BackupSchedule, _Mapping]]] = ...) -> None: ...

class DeleteBackupScheduleRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class CreateIndexRequest(_message.Message):
    __slots__ = ("parent", "index")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    parent: str
    index: _index_pb2.Index
    def __init__(self, parent: _Optional[str] = ..., index: _Optional[_Union[_index_pb2.Index, _Mapping]] = ...) -> None: ...

class ListIndexesRequest(_message.Message):
    __slots__ = ("parent", "filter", "page_size", "page_token")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    parent: str
    filter: str
    page_size: int
    page_token: str
    def __init__(self, parent: _Optional[str] = ..., filter: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListIndexesResponse(_message.Message):
    __slots__ = ("indexes", "next_page_token")
    INDEXES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    indexes: _containers.RepeatedCompositeFieldContainer[_index_pb2.Index]
    next_page_token: str
    def __init__(self, indexes: _Optional[_Iterable[_Union[_index_pb2.Index, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class GetIndexRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class DeleteIndexRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class UpdateFieldRequest(_message.Message):
    __slots__ = ("field", "update_mask")
    FIELD_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    field: _field_pb2.Field
    update_mask: _field_mask_pb2.FieldMask
    def __init__(self, field: _Optional[_Union[_field_pb2.Field, _Mapping]] = ..., update_mask: _Optional[_Union[_field_mask_pb2.FieldMask, _Mapping]] = ...) -> None: ...

class GetFieldRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListFieldsRequest(_message.Message):
    __slots__ = ("parent", "filter", "page_size", "page_token")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    parent: str
    filter: str
    page_size: int
    page_token: str
    def __init__(self, parent: _Optional[str] = ..., filter: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListFieldsResponse(_message.Message):
    __slots__ = ("fields", "next_page_token")
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    fields: _containers.RepeatedCompositeFieldContainer[_field_pb2.Field]
    next_page_token: str
    def __init__(self, fields: _Optional[_Iterable[_Union[_field_pb2.Field, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class ExportDocumentsRequest(_message.Message):
    __slots__ = ("name", "collection_ids", "output_uri_prefix", "namespace_ids", "snapshot_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_IDS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_URI_PREFIX_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_IDS_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    collection_ids: _containers.RepeatedScalarFieldContainer[str]
    output_uri_prefix: str
    namespace_ids: _containers.RepeatedScalarFieldContainer[str]
    snapshot_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., collection_ids: _Optional[_Iterable[str]] = ..., output_uri_prefix: _Optional[str] = ..., namespace_ids: _Optional[_Iterable[str]] = ..., snapshot_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ImportDocumentsRequest(_message.Message):
    __slots__ = ("name", "collection_ids", "input_uri_prefix", "namespace_ids")
    NAME_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_IDS_FIELD_NUMBER: _ClassVar[int]
    INPUT_URI_PREFIX_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_IDS_FIELD_NUMBER: _ClassVar[int]
    name: str
    collection_ids: _containers.RepeatedScalarFieldContainer[str]
    input_uri_prefix: str
    namespace_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., collection_ids: _Optional[_Iterable[str]] = ..., input_uri_prefix: _Optional[str] = ..., namespace_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class BulkDeleteDocumentsRequest(_message.Message):
    __slots__ = ("name", "collection_ids", "namespace_ids")
    NAME_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_IDS_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_IDS_FIELD_NUMBER: _ClassVar[int]
    name: str
    collection_ids: _containers.RepeatedScalarFieldContainer[str]
    namespace_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., collection_ids: _Optional[_Iterable[str]] = ..., namespace_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class BulkDeleteDocumentsResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetBackupRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListBackupsRequest(_message.Message):
    __slots__ = ("parent", "filter")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    parent: str
    filter: str
    def __init__(self, parent: _Optional[str] = ..., filter: _Optional[str] = ...) -> None: ...

class ListBackupsResponse(_message.Message):
    __slots__ = ("backups", "unreachable")
    BACKUPS_FIELD_NUMBER: _ClassVar[int]
    UNREACHABLE_FIELD_NUMBER: _ClassVar[int]
    backups: _containers.RepeatedCompositeFieldContainer[_backup_pb2.Backup]
    unreachable: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, backups: _Optional[_Iterable[_Union[_backup_pb2.Backup, _Mapping]]] = ..., unreachable: _Optional[_Iterable[str]] = ...) -> None: ...

class DeleteBackupRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class RestoreDatabaseRequest(_message.Message):
    __slots__ = ("parent", "database_id", "backup", "encryption_config", "tags")
    class TagsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PARENT_FIELD_NUMBER: _ClassVar[int]
    DATABASE_ID_FIELD_NUMBER: _ClassVar[int]
    BACKUP_FIELD_NUMBER: _ClassVar[int]
    ENCRYPTION_CONFIG_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    parent: str
    database_id: str
    backup: str
    encryption_config: _database_pb2.Database.EncryptionConfig
    tags: _containers.ScalarMap[str, str]
    def __init__(self, parent: _Optional[str] = ..., database_id: _Optional[str] = ..., backup: _Optional[str] = ..., encryption_config: _Optional[_Union[_database_pb2.Database.EncryptionConfig, _Mapping]] = ..., tags: _Optional[_Mapping[str, str]] = ...) -> None: ...

class CloneDatabaseRequest(_message.Message):
    __slots__ = ("parent", "database_id", "pitr_snapshot", "encryption_config", "tags")
    class TagsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PARENT_FIELD_NUMBER: _ClassVar[int]
    DATABASE_ID_FIELD_NUMBER: _ClassVar[int]
    PITR_SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    ENCRYPTION_CONFIG_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    parent: str
    database_id: str
    pitr_snapshot: _snapshot_pb2.PitrSnapshot
    encryption_config: _database_pb2.Database.EncryptionConfig
    tags: _containers.ScalarMap[str, str]
    def __init__(self, parent: _Optional[str] = ..., database_id: _Optional[str] = ..., pitr_snapshot: _Optional[_Union[_snapshot_pb2.PitrSnapshot, _Mapping]] = ..., encryption_config: _Optional[_Union[_database_pb2.Database.EncryptionConfig, _Mapping]] = ..., tags: _Optional[_Mapping[str, str]] = ...) -> None: ...
