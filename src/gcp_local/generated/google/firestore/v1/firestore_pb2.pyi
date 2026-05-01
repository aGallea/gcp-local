import datetime

from google.api import annotations_pb2 as _annotations_pb2
from google.api import client_pb2 as _client_pb2
from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import routing_pb2 as _routing_pb2
from google.firestore.v1 import aggregation_result_pb2 as _aggregation_result_pb2
from google.firestore.v1 import common_pb2 as _common_pb2
from google.firestore.v1 import document_pb2 as _document_pb2
from google.firestore.v1 import explain_stats_pb2 as _explain_stats_pb2
from google.firestore.v1 import pipeline_pb2 as _pipeline_pb2
from google.firestore.v1 import query_pb2 as _query_pb2
from google.firestore.v1 import query_profile_pb2 as _query_profile_pb2
from google.firestore.v1 import write_pb2 as _write_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf import wrappers_pb2 as _wrappers_pb2
from google.rpc import status_pb2 as _status_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GetDocumentRequest(_message.Message):
    __slots__ = ("name", "mask", "transaction", "read_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    MASK_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    mask: _common_pb2.DocumentMask
    transaction: bytes
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., mask: _Optional[_Union[_common_pb2.DocumentMask, _Mapping]] = ..., transaction: _Optional[bytes] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ListDocumentsRequest(_message.Message):
    __slots__ = ("parent", "collection_id", "page_size", "page_token", "order_by", "mask", "transaction", "read_time", "show_missing")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    MASK_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    SHOW_MISSING_FIELD_NUMBER: _ClassVar[int]
    parent: str
    collection_id: str
    page_size: int
    page_token: str
    order_by: str
    mask: _common_pb2.DocumentMask
    transaction: bytes
    read_time: _timestamp_pb2.Timestamp
    show_missing: bool
    def __init__(self, parent: _Optional[str] = ..., collection_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., order_by: _Optional[str] = ..., mask: _Optional[_Union[_common_pb2.DocumentMask, _Mapping]] = ..., transaction: _Optional[bytes] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., show_missing: bool = ...) -> None: ...

class ListDocumentsResponse(_message.Message):
    __slots__ = ("documents", "next_page_token")
    DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    documents: _containers.RepeatedCompositeFieldContainer[_document_pb2.Document]
    next_page_token: str
    def __init__(self, documents: _Optional[_Iterable[_Union[_document_pb2.Document, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class CreateDocumentRequest(_message.Message):
    __slots__ = ("parent", "collection_id", "document_id", "document", "mask")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    MASK_FIELD_NUMBER: _ClassVar[int]
    parent: str
    collection_id: str
    document_id: str
    document: _document_pb2.Document
    mask: _common_pb2.DocumentMask
    def __init__(self, parent: _Optional[str] = ..., collection_id: _Optional[str] = ..., document_id: _Optional[str] = ..., document: _Optional[_Union[_document_pb2.Document, _Mapping]] = ..., mask: _Optional[_Union[_common_pb2.DocumentMask, _Mapping]] = ...) -> None: ...

class UpdateDocumentRequest(_message.Message):
    __slots__ = ("document", "update_mask", "mask", "current_document")
    DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    MASK_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    document: _document_pb2.Document
    update_mask: _common_pb2.DocumentMask
    mask: _common_pb2.DocumentMask
    current_document: _common_pb2.Precondition
    def __init__(self, document: _Optional[_Union[_document_pb2.Document, _Mapping]] = ..., update_mask: _Optional[_Union[_common_pb2.DocumentMask, _Mapping]] = ..., mask: _Optional[_Union[_common_pb2.DocumentMask, _Mapping]] = ..., current_document: _Optional[_Union[_common_pb2.Precondition, _Mapping]] = ...) -> None: ...

class DeleteDocumentRequest(_message.Message):
    __slots__ = ("name", "current_document")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    name: str
    current_document: _common_pb2.Precondition
    def __init__(self, name: _Optional[str] = ..., current_document: _Optional[_Union[_common_pb2.Precondition, _Mapping]] = ...) -> None: ...

class BatchGetDocumentsRequest(_message.Message):
    __slots__ = ("database", "documents", "mask", "transaction", "new_transaction", "read_time")
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    MASK_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    NEW_TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    database: str
    documents: _containers.RepeatedScalarFieldContainer[str]
    mask: _common_pb2.DocumentMask
    transaction: bytes
    new_transaction: _common_pb2.TransactionOptions
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, database: _Optional[str] = ..., documents: _Optional[_Iterable[str]] = ..., mask: _Optional[_Union[_common_pb2.DocumentMask, _Mapping]] = ..., transaction: _Optional[bytes] = ..., new_transaction: _Optional[_Union[_common_pb2.TransactionOptions, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class BatchGetDocumentsResponse(_message.Message):
    __slots__ = ("found", "missing", "transaction", "read_time")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    MISSING_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    found: _document_pb2.Document
    missing: str
    transaction: bytes
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, found: _Optional[_Union[_document_pb2.Document, _Mapping]] = ..., missing: _Optional[str] = ..., transaction: _Optional[bytes] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class BeginTransactionRequest(_message.Message):
    __slots__ = ("database", "options")
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    database: str
    options: _common_pb2.TransactionOptions
    def __init__(self, database: _Optional[str] = ..., options: _Optional[_Union[_common_pb2.TransactionOptions, _Mapping]] = ...) -> None: ...

class BeginTransactionResponse(_message.Message):
    __slots__ = ("transaction",)
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    transaction: bytes
    def __init__(self, transaction: _Optional[bytes] = ...) -> None: ...

class CommitRequest(_message.Message):
    __slots__ = ("database", "writes", "transaction")
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    WRITES_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    database: str
    writes: _containers.RepeatedCompositeFieldContainer[_write_pb2.Write]
    transaction: bytes
    def __init__(self, database: _Optional[str] = ..., writes: _Optional[_Iterable[_Union[_write_pb2.Write, _Mapping]]] = ..., transaction: _Optional[bytes] = ...) -> None: ...

class CommitResponse(_message.Message):
    __slots__ = ("write_results", "commit_time")
    WRITE_RESULTS_FIELD_NUMBER: _ClassVar[int]
    COMMIT_TIME_FIELD_NUMBER: _ClassVar[int]
    write_results: _containers.RepeatedCompositeFieldContainer[_write_pb2.WriteResult]
    commit_time: _timestamp_pb2.Timestamp
    def __init__(self, write_results: _Optional[_Iterable[_Union[_write_pb2.WriteResult, _Mapping]]] = ..., commit_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class RollbackRequest(_message.Message):
    __slots__ = ("database", "transaction")
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    database: str
    transaction: bytes
    def __init__(self, database: _Optional[str] = ..., transaction: _Optional[bytes] = ...) -> None: ...

class RunQueryRequest(_message.Message):
    __slots__ = ("parent", "structured_query", "transaction", "new_transaction", "read_time", "explain_options")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    STRUCTURED_QUERY_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    NEW_TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    EXPLAIN_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    parent: str
    structured_query: _query_pb2.StructuredQuery
    transaction: bytes
    new_transaction: _common_pb2.TransactionOptions
    read_time: _timestamp_pb2.Timestamp
    explain_options: _query_profile_pb2.ExplainOptions
    def __init__(self, parent: _Optional[str] = ..., structured_query: _Optional[_Union[_query_pb2.StructuredQuery, _Mapping]] = ..., transaction: _Optional[bytes] = ..., new_transaction: _Optional[_Union[_common_pb2.TransactionOptions, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., explain_options: _Optional[_Union[_query_profile_pb2.ExplainOptions, _Mapping]] = ...) -> None: ...

class RunQueryResponse(_message.Message):
    __slots__ = ("transaction", "document", "read_time", "skipped_results", "done", "explain_metrics")
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_RESULTS_FIELD_NUMBER: _ClassVar[int]
    DONE_FIELD_NUMBER: _ClassVar[int]
    EXPLAIN_METRICS_FIELD_NUMBER: _ClassVar[int]
    transaction: bytes
    document: _document_pb2.Document
    read_time: _timestamp_pb2.Timestamp
    skipped_results: int
    done: bool
    explain_metrics: _query_profile_pb2.ExplainMetrics
    def __init__(self, transaction: _Optional[bytes] = ..., document: _Optional[_Union[_document_pb2.Document, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., skipped_results: _Optional[int] = ..., done: bool = ..., explain_metrics: _Optional[_Union[_query_profile_pb2.ExplainMetrics, _Mapping]] = ...) -> None: ...

class ExecutePipelineRequest(_message.Message):
    __slots__ = ("database", "structured_pipeline", "transaction", "new_transaction", "read_time")
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    STRUCTURED_PIPELINE_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    NEW_TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    database: str
    structured_pipeline: _pipeline_pb2.StructuredPipeline
    transaction: bytes
    new_transaction: _common_pb2.TransactionOptions
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, database: _Optional[str] = ..., structured_pipeline: _Optional[_Union[_pipeline_pb2.StructuredPipeline, _Mapping]] = ..., transaction: _Optional[bytes] = ..., new_transaction: _Optional[_Union[_common_pb2.TransactionOptions, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ExecutePipelineResponse(_message.Message):
    __slots__ = ("transaction", "results", "execution_time", "explain_stats")
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_TIME_FIELD_NUMBER: _ClassVar[int]
    EXPLAIN_STATS_FIELD_NUMBER: _ClassVar[int]
    transaction: bytes
    results: _containers.RepeatedCompositeFieldContainer[_document_pb2.Document]
    execution_time: _timestamp_pb2.Timestamp
    explain_stats: _explain_stats_pb2.ExplainStats
    def __init__(self, transaction: _Optional[bytes] = ..., results: _Optional[_Iterable[_Union[_document_pb2.Document, _Mapping]]] = ..., execution_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., explain_stats: _Optional[_Union[_explain_stats_pb2.ExplainStats, _Mapping]] = ...) -> None: ...

class RunAggregationQueryRequest(_message.Message):
    __slots__ = ("parent", "structured_aggregation_query", "transaction", "new_transaction", "read_time", "explain_options")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    STRUCTURED_AGGREGATION_QUERY_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    NEW_TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    EXPLAIN_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    parent: str
    structured_aggregation_query: _query_pb2.StructuredAggregationQuery
    transaction: bytes
    new_transaction: _common_pb2.TransactionOptions
    read_time: _timestamp_pb2.Timestamp
    explain_options: _query_profile_pb2.ExplainOptions
    def __init__(self, parent: _Optional[str] = ..., structured_aggregation_query: _Optional[_Union[_query_pb2.StructuredAggregationQuery, _Mapping]] = ..., transaction: _Optional[bytes] = ..., new_transaction: _Optional[_Union[_common_pb2.TransactionOptions, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., explain_options: _Optional[_Union[_query_profile_pb2.ExplainOptions, _Mapping]] = ...) -> None: ...

class RunAggregationQueryResponse(_message.Message):
    __slots__ = ("result", "transaction", "read_time", "explain_metrics")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    EXPLAIN_METRICS_FIELD_NUMBER: _ClassVar[int]
    result: _aggregation_result_pb2.AggregationResult
    transaction: bytes
    read_time: _timestamp_pb2.Timestamp
    explain_metrics: _query_profile_pb2.ExplainMetrics
    def __init__(self, result: _Optional[_Union[_aggregation_result_pb2.AggregationResult, _Mapping]] = ..., transaction: _Optional[bytes] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., explain_metrics: _Optional[_Union[_query_profile_pb2.ExplainMetrics, _Mapping]] = ...) -> None: ...

class PartitionQueryRequest(_message.Message):
    __slots__ = ("parent", "structured_query", "partition_count", "page_token", "page_size", "read_time")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    STRUCTURED_QUERY_FIELD_NUMBER: _ClassVar[int]
    PARTITION_COUNT_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    parent: str
    structured_query: _query_pb2.StructuredQuery
    partition_count: int
    page_token: str
    page_size: int
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, parent: _Optional[str] = ..., structured_query: _Optional[_Union[_query_pb2.StructuredQuery, _Mapping]] = ..., partition_count: _Optional[int] = ..., page_token: _Optional[str] = ..., page_size: _Optional[int] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class PartitionQueryResponse(_message.Message):
    __slots__ = ("partitions", "next_page_token")
    PARTITIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    partitions: _containers.RepeatedCompositeFieldContainer[_query_pb2.Cursor]
    next_page_token: str
    def __init__(self, partitions: _Optional[_Iterable[_Union[_query_pb2.Cursor, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class WriteRequest(_message.Message):
    __slots__ = ("database", "stream_id", "writes", "stream_token", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    WRITES_FIELD_NUMBER: _ClassVar[int]
    STREAM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    database: str
    stream_id: str
    writes: _containers.RepeatedCompositeFieldContainer[_write_pb2.Write]
    stream_token: bytes
    labels: _containers.ScalarMap[str, str]
    def __init__(self, database: _Optional[str] = ..., stream_id: _Optional[str] = ..., writes: _Optional[_Iterable[_Union[_write_pb2.Write, _Mapping]]] = ..., stream_token: _Optional[bytes] = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...

class WriteResponse(_message.Message):
    __slots__ = ("stream_id", "stream_token", "write_results", "commit_time")
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    STREAM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    WRITE_RESULTS_FIELD_NUMBER: _ClassVar[int]
    COMMIT_TIME_FIELD_NUMBER: _ClassVar[int]
    stream_id: str
    stream_token: bytes
    write_results: _containers.RepeatedCompositeFieldContainer[_write_pb2.WriteResult]
    commit_time: _timestamp_pb2.Timestamp
    def __init__(self, stream_id: _Optional[str] = ..., stream_token: _Optional[bytes] = ..., write_results: _Optional[_Iterable[_Union[_write_pb2.WriteResult, _Mapping]]] = ..., commit_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ListenRequest(_message.Message):
    __slots__ = ("database", "add_target", "remove_target", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    ADD_TARGET_FIELD_NUMBER: _ClassVar[int]
    REMOVE_TARGET_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    database: str
    add_target: Target
    remove_target: int
    labels: _containers.ScalarMap[str, str]
    def __init__(self, database: _Optional[str] = ..., add_target: _Optional[_Union[Target, _Mapping]] = ..., remove_target: _Optional[int] = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ListenResponse(_message.Message):
    __slots__ = ("target_change", "document_change", "document_delete", "document_remove", "filter")
    TARGET_CHANGE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_CHANGE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_DELETE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_REMOVE_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    target_change: TargetChange
    document_change: _write_pb2.DocumentChange
    document_delete: _write_pb2.DocumentDelete
    document_remove: _write_pb2.DocumentRemove
    filter: _write_pb2.ExistenceFilter
    def __init__(self, target_change: _Optional[_Union[TargetChange, _Mapping]] = ..., document_change: _Optional[_Union[_write_pb2.DocumentChange, _Mapping]] = ..., document_delete: _Optional[_Union[_write_pb2.DocumentDelete, _Mapping]] = ..., document_remove: _Optional[_Union[_write_pb2.DocumentRemove, _Mapping]] = ..., filter: _Optional[_Union[_write_pb2.ExistenceFilter, _Mapping]] = ...) -> None: ...

class Target(_message.Message):
    __slots__ = ("query", "documents", "resume_token", "read_time", "target_id", "once", "expected_count")
    class DocumentsTarget(_message.Message):
        __slots__ = ("documents",)
        DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
        documents: _containers.RepeatedScalarFieldContainer[str]
        def __init__(self, documents: _Optional[_Iterable[str]] = ...) -> None: ...
    class QueryTarget(_message.Message):
        __slots__ = ("parent", "structured_query")
        PARENT_FIELD_NUMBER: _ClassVar[int]
        STRUCTURED_QUERY_FIELD_NUMBER: _ClassVar[int]
        parent: str
        structured_query: _query_pb2.StructuredQuery
        def __init__(self, parent: _Optional[str] = ..., structured_query: _Optional[_Union[_query_pb2.StructuredQuery, _Mapping]] = ...) -> None: ...
    QUERY_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    RESUME_TOKEN_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    ONCE_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_COUNT_FIELD_NUMBER: _ClassVar[int]
    query: Target.QueryTarget
    documents: Target.DocumentsTarget
    resume_token: bytes
    read_time: _timestamp_pb2.Timestamp
    target_id: int
    once: bool
    expected_count: _wrappers_pb2.Int32Value
    def __init__(self, query: _Optional[_Union[Target.QueryTarget, _Mapping]] = ..., documents: _Optional[_Union[Target.DocumentsTarget, _Mapping]] = ..., resume_token: _Optional[bytes] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., target_id: _Optional[int] = ..., once: bool = ..., expected_count: _Optional[_Union[_wrappers_pb2.Int32Value, _Mapping]] = ...) -> None: ...

class TargetChange(_message.Message):
    __slots__ = ("target_change_type", "target_ids", "cause", "resume_token", "read_time")
    class TargetChangeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        NO_CHANGE: _ClassVar[TargetChange.TargetChangeType]
        ADD: _ClassVar[TargetChange.TargetChangeType]
        REMOVE: _ClassVar[TargetChange.TargetChangeType]
        CURRENT: _ClassVar[TargetChange.TargetChangeType]
        RESET: _ClassVar[TargetChange.TargetChangeType]
    NO_CHANGE: TargetChange.TargetChangeType
    ADD: TargetChange.TargetChangeType
    REMOVE: TargetChange.TargetChangeType
    CURRENT: TargetChange.TargetChangeType
    RESET: TargetChange.TargetChangeType
    TARGET_CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_IDS_FIELD_NUMBER: _ClassVar[int]
    CAUSE_FIELD_NUMBER: _ClassVar[int]
    RESUME_TOKEN_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    target_change_type: TargetChange.TargetChangeType
    target_ids: _containers.RepeatedScalarFieldContainer[int]
    cause: _status_pb2.Status
    resume_token: bytes
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, target_change_type: _Optional[_Union[TargetChange.TargetChangeType, str]] = ..., target_ids: _Optional[_Iterable[int]] = ..., cause: _Optional[_Union[_status_pb2.Status, _Mapping]] = ..., resume_token: _Optional[bytes] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ListCollectionIdsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "read_time")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ListCollectionIdsResponse(_message.Message):
    __slots__ = ("collection_ids", "next_page_token")
    COLLECTION_IDS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    collection_ids: _containers.RepeatedScalarFieldContainer[str]
    next_page_token: str
    def __init__(self, collection_ids: _Optional[_Iterable[str]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class BatchWriteRequest(_message.Message):
    __slots__ = ("database", "writes", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    WRITES_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    database: str
    writes: _containers.RepeatedCompositeFieldContainer[_write_pb2.Write]
    labels: _containers.ScalarMap[str, str]
    def __init__(self, database: _Optional[str] = ..., writes: _Optional[_Iterable[_Union[_write_pb2.Write, _Mapping]]] = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...

class BatchWriteResponse(_message.Message):
    __slots__ = ("write_results", "status")
    WRITE_RESULTS_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    write_results: _containers.RepeatedCompositeFieldContainer[_write_pb2.WriteResult]
    status: _containers.RepeatedCompositeFieldContainer[_status_pb2.Status]
    def __init__(self, write_results: _Optional[_Iterable[_Union[_write_pb2.WriteResult, _Mapping]]] = ..., status: _Optional[_Iterable[_Union[_status_pb2.Status, _Mapping]]] = ...) -> None: ...
