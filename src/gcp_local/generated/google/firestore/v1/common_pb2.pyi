import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DocumentMask(_message.Message):
    __slots__ = ("field_paths",)
    FIELD_PATHS_FIELD_NUMBER: _ClassVar[int]
    field_paths: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, field_paths: _Optional[_Iterable[str]] = ...) -> None: ...

class Precondition(_message.Message):
    __slots__ = ("exists", "update_time")
    EXISTS_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    exists: bool
    update_time: _timestamp_pb2.Timestamp
    def __init__(self, exists: bool = ..., update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class TransactionOptions(_message.Message):
    __slots__ = ("read_only", "read_write")
    class ReadWrite(_message.Message):
        __slots__ = ("retry_transaction",)
        RETRY_TRANSACTION_FIELD_NUMBER: _ClassVar[int]
        retry_transaction: bytes
        def __init__(self, retry_transaction: _Optional[bytes] = ...) -> None: ...
    class ReadOnly(_message.Message):
        __slots__ = ("read_time",)
        READ_TIME_FIELD_NUMBER: _ClassVar[int]
        read_time: _timestamp_pb2.Timestamp
        def __init__(self, read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
    READ_ONLY_FIELD_NUMBER: _ClassVar[int]
    READ_WRITE_FIELD_NUMBER: _ClassVar[int]
    read_only: TransactionOptions.ReadOnly
    read_write: TransactionOptions.ReadWrite
    def __init__(self, read_only: _Optional[_Union[TransactionOptions.ReadOnly, _Mapping]] = ..., read_write: _Optional[_Union[TransactionOptions.ReadWrite, _Mapping]] = ...) -> None: ...
