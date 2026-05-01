from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.firestore.v1 import document_pb2 as _document_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StructuredPipeline(_message.Message):
    __slots__ = ("pipeline", "options")
    class OptionsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: _document_pb2.Value
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[_document_pb2.Value, _Mapping]] = ...) -> None: ...
    PIPELINE_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    pipeline: _document_pb2.Pipeline
    options: _containers.MessageMap[str, _document_pb2.Value]
    def __init__(self, pipeline: _Optional[_Union[_document_pb2.Pipeline, _Mapping]] = ..., options: _Optional[_Mapping[str, _document_pb2.Value]] = ...) -> None: ...
