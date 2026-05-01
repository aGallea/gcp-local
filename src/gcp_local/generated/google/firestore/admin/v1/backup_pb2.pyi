import datetime

from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Backup(_message.Message):
    __slots__ = ("name", "database", "database_uid", "snapshot_time", "expire_time", "stats", "state")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[Backup.State]
        CREATING: _ClassVar[Backup.State]
        READY: _ClassVar[Backup.State]
        NOT_AVAILABLE: _ClassVar[Backup.State]
    STATE_UNSPECIFIED: Backup.State
    CREATING: Backup.State
    READY: Backup.State
    NOT_AVAILABLE: Backup.State
    class Stats(_message.Message):
        __slots__ = ("size_bytes", "document_count", "index_count")
        SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
        DOCUMENT_COUNT_FIELD_NUMBER: _ClassVar[int]
        INDEX_COUNT_FIELD_NUMBER: _ClassVar[int]
        size_bytes: int
        document_count: int
        index_count: int
        def __init__(self, size_bytes: _Optional[int] = ..., document_count: _Optional[int] = ..., index_count: _Optional[int] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    DATABASE_UID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_TIME_FIELD_NUMBER: _ClassVar[int]
    EXPIRE_TIME_FIELD_NUMBER: _ClassVar[int]
    STATS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    name: str
    database: str
    database_uid: str
    snapshot_time: _timestamp_pb2.Timestamp
    expire_time: _timestamp_pb2.Timestamp
    stats: Backup.Stats
    state: Backup.State
    def __init__(self, name: _Optional[str] = ..., database: _Optional[str] = ..., database_uid: _Optional[str] = ..., snapshot_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., expire_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., stats: _Optional[_Union[Backup.Stats, _Mapping]] = ..., state: _Optional[_Union[Backup.State, str]] = ...) -> None: ...
