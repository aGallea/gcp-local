import datetime

from google.firestore.v1 import bloom_filter_pb2 as _bloom_filter_pb2
from google.firestore.v1 import common_pb2 as _common_pb2
from google.firestore.v1 import document_pb2 as _document_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Write(_message.Message):
    __slots__ = ("update", "delete", "transform", "update_mask", "update_transforms", "current_document")
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    DELETE_FIELD_NUMBER: _ClassVar[int]
    TRANSFORM_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TRANSFORMS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    update: _document_pb2.Document
    delete: str
    transform: DocumentTransform
    update_mask: _common_pb2.DocumentMask
    update_transforms: _containers.RepeatedCompositeFieldContainer[DocumentTransform.FieldTransform]
    current_document: _common_pb2.Precondition
    def __init__(self, update: _Optional[_Union[_document_pb2.Document, _Mapping]] = ..., delete: _Optional[str] = ..., transform: _Optional[_Union[DocumentTransform, _Mapping]] = ..., update_mask: _Optional[_Union[_common_pb2.DocumentMask, _Mapping]] = ..., update_transforms: _Optional[_Iterable[_Union[DocumentTransform.FieldTransform, _Mapping]]] = ..., current_document: _Optional[_Union[_common_pb2.Precondition, _Mapping]] = ...) -> None: ...

class DocumentTransform(_message.Message):
    __slots__ = ("document", "field_transforms")
    class FieldTransform(_message.Message):
        __slots__ = ("field_path", "set_to_server_value", "increment", "maximum", "minimum", "append_missing_elements", "remove_all_from_array")
        class ServerValue(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            SERVER_VALUE_UNSPECIFIED: _ClassVar[DocumentTransform.FieldTransform.ServerValue]
            REQUEST_TIME: _ClassVar[DocumentTransform.FieldTransform.ServerValue]
        SERVER_VALUE_UNSPECIFIED: DocumentTransform.FieldTransform.ServerValue
        REQUEST_TIME: DocumentTransform.FieldTransform.ServerValue
        FIELD_PATH_FIELD_NUMBER: _ClassVar[int]
        SET_TO_SERVER_VALUE_FIELD_NUMBER: _ClassVar[int]
        INCREMENT_FIELD_NUMBER: _ClassVar[int]
        MAXIMUM_FIELD_NUMBER: _ClassVar[int]
        MINIMUM_FIELD_NUMBER: _ClassVar[int]
        APPEND_MISSING_ELEMENTS_FIELD_NUMBER: _ClassVar[int]
        REMOVE_ALL_FROM_ARRAY_FIELD_NUMBER: _ClassVar[int]
        field_path: str
        set_to_server_value: DocumentTransform.FieldTransform.ServerValue
        increment: _document_pb2.Value
        maximum: _document_pb2.Value
        minimum: _document_pb2.Value
        append_missing_elements: _document_pb2.ArrayValue
        remove_all_from_array: _document_pb2.ArrayValue
        def __init__(self, field_path: _Optional[str] = ..., set_to_server_value: _Optional[_Union[DocumentTransform.FieldTransform.ServerValue, str]] = ..., increment: _Optional[_Union[_document_pb2.Value, _Mapping]] = ..., maximum: _Optional[_Union[_document_pb2.Value, _Mapping]] = ..., minimum: _Optional[_Union[_document_pb2.Value, _Mapping]] = ..., append_missing_elements: _Optional[_Union[_document_pb2.ArrayValue, _Mapping]] = ..., remove_all_from_array: _Optional[_Union[_document_pb2.ArrayValue, _Mapping]] = ...) -> None: ...
    DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    FIELD_TRANSFORMS_FIELD_NUMBER: _ClassVar[int]
    document: str
    field_transforms: _containers.RepeatedCompositeFieldContainer[DocumentTransform.FieldTransform]
    def __init__(self, document: _Optional[str] = ..., field_transforms: _Optional[_Iterable[_Union[DocumentTransform.FieldTransform, _Mapping]]] = ...) -> None: ...

class WriteResult(_message.Message):
    __slots__ = ("update_time", "transform_results")
    UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    TRANSFORM_RESULTS_FIELD_NUMBER: _ClassVar[int]
    update_time: _timestamp_pb2.Timestamp
    transform_results: _containers.RepeatedCompositeFieldContainer[_document_pb2.Value]
    def __init__(self, update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., transform_results: _Optional[_Iterable[_Union[_document_pb2.Value, _Mapping]]] = ...) -> None: ...

class DocumentChange(_message.Message):
    __slots__ = ("document", "target_ids", "removed_target_ids")
    DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    TARGET_IDS_FIELD_NUMBER: _ClassVar[int]
    REMOVED_TARGET_IDS_FIELD_NUMBER: _ClassVar[int]
    document: _document_pb2.Document
    target_ids: _containers.RepeatedScalarFieldContainer[int]
    removed_target_ids: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, document: _Optional[_Union[_document_pb2.Document, _Mapping]] = ..., target_ids: _Optional[_Iterable[int]] = ..., removed_target_ids: _Optional[_Iterable[int]] = ...) -> None: ...

class DocumentDelete(_message.Message):
    __slots__ = ("document", "removed_target_ids", "read_time")
    DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    REMOVED_TARGET_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    document: str
    removed_target_ids: _containers.RepeatedScalarFieldContainer[int]
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, document: _Optional[str] = ..., removed_target_ids: _Optional[_Iterable[int]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class DocumentRemove(_message.Message):
    __slots__ = ("document", "removed_target_ids", "read_time")
    DOCUMENT_FIELD_NUMBER: _ClassVar[int]
    REMOVED_TARGET_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    document: str
    removed_target_ids: _containers.RepeatedScalarFieldContainer[int]
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, document: _Optional[str] = ..., removed_target_ids: _Optional[_Iterable[int]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ExistenceFilter(_message.Message):
    __slots__ = ("target_id", "count", "unchanged_names")
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    UNCHANGED_NAMES_FIELD_NUMBER: _ClassVar[int]
    target_id: int
    count: int
    unchanged_names: _bloom_filter_pb2.BloomFilter
    def __init__(self, target_id: _Optional[int] = ..., count: _Optional[int] = ..., unchanged_names: _Optional[_Union[_bloom_filter_pb2.BloomFilter, _Mapping]] = ...) -> None: ...
