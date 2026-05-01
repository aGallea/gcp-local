import datetime

from google.api import resource_pb2 as _resource_pb2
from google.firestore.admin.v1 import index_pb2 as _index_pb2
from google.firestore.admin.v1 import snapshot_pb2 as _snapshot_pb2
from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class OperationState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OPERATION_STATE_UNSPECIFIED: _ClassVar[OperationState]
    INITIALIZING: _ClassVar[OperationState]
    PROCESSING: _ClassVar[OperationState]
    CANCELLING: _ClassVar[OperationState]
    FINALIZING: _ClassVar[OperationState]
    SUCCESSFUL: _ClassVar[OperationState]
    FAILED: _ClassVar[OperationState]
    CANCELLED: _ClassVar[OperationState]
OPERATION_STATE_UNSPECIFIED: OperationState
INITIALIZING: OperationState
PROCESSING: OperationState
CANCELLING: OperationState
FINALIZING: OperationState
SUCCESSFUL: OperationState
FAILED: OperationState
CANCELLED: OperationState

class IndexOperationMetadata(_message.Message):
    __slots__ = ("start_time", "end_time", "index", "state", "progress_documents", "progress_bytes")
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_BYTES_FIELD_NUMBER: _ClassVar[int]
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    index: str
    state: OperationState
    progress_documents: Progress
    progress_bytes: Progress
    def __init__(self, start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., index: _Optional[str] = ..., state: _Optional[_Union[OperationState, str]] = ..., progress_documents: _Optional[_Union[Progress, _Mapping]] = ..., progress_bytes: _Optional[_Union[Progress, _Mapping]] = ...) -> None: ...

class FieldOperationMetadata(_message.Message):
    __slots__ = ("start_time", "end_time", "field", "index_config_deltas", "state", "progress_documents", "progress_bytes", "ttl_config_delta")
    class IndexConfigDelta(_message.Message):
        __slots__ = ("change_type", "index")
        class ChangeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            CHANGE_TYPE_UNSPECIFIED: _ClassVar[FieldOperationMetadata.IndexConfigDelta.ChangeType]
            ADD: _ClassVar[FieldOperationMetadata.IndexConfigDelta.ChangeType]
            REMOVE: _ClassVar[FieldOperationMetadata.IndexConfigDelta.ChangeType]
        CHANGE_TYPE_UNSPECIFIED: FieldOperationMetadata.IndexConfigDelta.ChangeType
        ADD: FieldOperationMetadata.IndexConfigDelta.ChangeType
        REMOVE: FieldOperationMetadata.IndexConfigDelta.ChangeType
        CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
        INDEX_FIELD_NUMBER: _ClassVar[int]
        change_type: FieldOperationMetadata.IndexConfigDelta.ChangeType
        index: _index_pb2.Index
        def __init__(self, change_type: _Optional[_Union[FieldOperationMetadata.IndexConfigDelta.ChangeType, str]] = ..., index: _Optional[_Union[_index_pb2.Index, _Mapping]] = ...) -> None: ...
    class TtlConfigDelta(_message.Message):
        __slots__ = ("change_type", "expiration_offset")
        class ChangeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            CHANGE_TYPE_UNSPECIFIED: _ClassVar[FieldOperationMetadata.TtlConfigDelta.ChangeType]
            ADD: _ClassVar[FieldOperationMetadata.TtlConfigDelta.ChangeType]
            REMOVE: _ClassVar[FieldOperationMetadata.TtlConfigDelta.ChangeType]
        CHANGE_TYPE_UNSPECIFIED: FieldOperationMetadata.TtlConfigDelta.ChangeType
        ADD: FieldOperationMetadata.TtlConfigDelta.ChangeType
        REMOVE: FieldOperationMetadata.TtlConfigDelta.ChangeType
        CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
        EXPIRATION_OFFSET_FIELD_NUMBER: _ClassVar[int]
        change_type: FieldOperationMetadata.TtlConfigDelta.ChangeType
        expiration_offset: _duration_pb2.Duration
        def __init__(self, change_type: _Optional[_Union[FieldOperationMetadata.TtlConfigDelta.ChangeType, str]] = ..., expiration_offset: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    FIELD_FIELD_NUMBER: _ClassVar[int]
    INDEX_CONFIG_DELTAS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_BYTES_FIELD_NUMBER: _ClassVar[int]
    TTL_CONFIG_DELTA_FIELD_NUMBER: _ClassVar[int]
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    field: str
    index_config_deltas: _containers.RepeatedCompositeFieldContainer[FieldOperationMetadata.IndexConfigDelta]
    state: OperationState
    progress_documents: Progress
    progress_bytes: Progress
    ttl_config_delta: FieldOperationMetadata.TtlConfigDelta
    def __init__(self, start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., field: _Optional[str] = ..., index_config_deltas: _Optional[_Iterable[_Union[FieldOperationMetadata.IndexConfigDelta, _Mapping]]] = ..., state: _Optional[_Union[OperationState, str]] = ..., progress_documents: _Optional[_Union[Progress, _Mapping]] = ..., progress_bytes: _Optional[_Union[Progress, _Mapping]] = ..., ttl_config_delta: _Optional[_Union[FieldOperationMetadata.TtlConfigDelta, _Mapping]] = ...) -> None: ...

class ExportDocumentsMetadata(_message.Message):
    __slots__ = ("start_time", "end_time", "operation_state", "progress_documents", "progress_bytes", "collection_ids", "output_uri_prefix", "namespace_ids", "snapshot_time")
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    OPERATION_STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_BYTES_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_IDS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_URI_PREFIX_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_IDS_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_TIME_FIELD_NUMBER: _ClassVar[int]
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    operation_state: OperationState
    progress_documents: Progress
    progress_bytes: Progress
    collection_ids: _containers.RepeatedScalarFieldContainer[str]
    output_uri_prefix: str
    namespace_ids: _containers.RepeatedScalarFieldContainer[str]
    snapshot_time: _timestamp_pb2.Timestamp
    def __init__(self, start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., operation_state: _Optional[_Union[OperationState, str]] = ..., progress_documents: _Optional[_Union[Progress, _Mapping]] = ..., progress_bytes: _Optional[_Union[Progress, _Mapping]] = ..., collection_ids: _Optional[_Iterable[str]] = ..., output_uri_prefix: _Optional[str] = ..., namespace_ids: _Optional[_Iterable[str]] = ..., snapshot_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ImportDocumentsMetadata(_message.Message):
    __slots__ = ("start_time", "end_time", "operation_state", "progress_documents", "progress_bytes", "collection_ids", "input_uri_prefix", "namespace_ids")
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    OPERATION_STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_BYTES_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_IDS_FIELD_NUMBER: _ClassVar[int]
    INPUT_URI_PREFIX_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_IDS_FIELD_NUMBER: _ClassVar[int]
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    operation_state: OperationState
    progress_documents: Progress
    progress_bytes: Progress
    collection_ids: _containers.RepeatedScalarFieldContainer[str]
    input_uri_prefix: str
    namespace_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., operation_state: _Optional[_Union[OperationState, str]] = ..., progress_documents: _Optional[_Union[Progress, _Mapping]] = ..., progress_bytes: _Optional[_Union[Progress, _Mapping]] = ..., collection_ids: _Optional[_Iterable[str]] = ..., input_uri_prefix: _Optional[str] = ..., namespace_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class BulkDeleteDocumentsMetadata(_message.Message):
    __slots__ = ("start_time", "end_time", "operation_state", "progress_documents", "progress_bytes", "collection_ids", "namespace_ids", "snapshot_time")
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    OPERATION_STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_BYTES_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_IDS_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_IDS_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_TIME_FIELD_NUMBER: _ClassVar[int]
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    operation_state: OperationState
    progress_documents: Progress
    progress_bytes: Progress
    collection_ids: _containers.RepeatedScalarFieldContainer[str]
    namespace_ids: _containers.RepeatedScalarFieldContainer[str]
    snapshot_time: _timestamp_pb2.Timestamp
    def __init__(self, start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., operation_state: _Optional[_Union[OperationState, str]] = ..., progress_documents: _Optional[_Union[Progress, _Mapping]] = ..., progress_bytes: _Optional[_Union[Progress, _Mapping]] = ..., collection_ids: _Optional[_Iterable[str]] = ..., namespace_ids: _Optional[_Iterable[str]] = ..., snapshot_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ExportDocumentsResponse(_message.Message):
    __slots__ = ("output_uri_prefix",)
    OUTPUT_URI_PREFIX_FIELD_NUMBER: _ClassVar[int]
    output_uri_prefix: str
    def __init__(self, output_uri_prefix: _Optional[str] = ...) -> None: ...

class RestoreDatabaseMetadata(_message.Message):
    __slots__ = ("start_time", "end_time", "operation_state", "database", "backup", "progress_percentage")
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    OPERATION_STATE_FIELD_NUMBER: _ClassVar[int]
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    BACKUP_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_PERCENTAGE_FIELD_NUMBER: _ClassVar[int]
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    operation_state: OperationState
    database: str
    backup: str
    progress_percentage: Progress
    def __init__(self, start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., operation_state: _Optional[_Union[OperationState, str]] = ..., database: _Optional[str] = ..., backup: _Optional[str] = ..., progress_percentage: _Optional[_Union[Progress, _Mapping]] = ...) -> None: ...

class CloneDatabaseMetadata(_message.Message):
    __slots__ = ("start_time", "end_time", "operation_state", "database", "pitr_snapshot", "progress_percentage")
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    OPERATION_STATE_FIELD_NUMBER: _ClassVar[int]
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    PITR_SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_PERCENTAGE_FIELD_NUMBER: _ClassVar[int]
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    operation_state: OperationState
    database: str
    pitr_snapshot: _snapshot_pb2.PitrSnapshot
    progress_percentage: Progress
    def __init__(self, start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., operation_state: _Optional[_Union[OperationState, str]] = ..., database: _Optional[str] = ..., pitr_snapshot: _Optional[_Union[_snapshot_pb2.PitrSnapshot, _Mapping]] = ..., progress_percentage: _Optional[_Union[Progress, _Mapping]] = ...) -> None: ...

class Progress(_message.Message):
    __slots__ = ("estimated_work", "completed_work")
    ESTIMATED_WORK_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_WORK_FIELD_NUMBER: _ClassVar[int]
    estimated_work: int
    completed_work: int
    def __init__(self, estimated_work: _Optional[int] = ..., completed_work: _Optional[int] = ...) -> None: ...
