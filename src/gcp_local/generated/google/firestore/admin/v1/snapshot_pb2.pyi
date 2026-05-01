import datetime

from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PitrSnapshot(_message.Message):
    __slots__ = ("database", "database_uid", "snapshot_time")
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    DATABASE_UID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_TIME_FIELD_NUMBER: _ClassVar[int]
    database: str
    database_uid: bytes
    snapshot_time: _timestamp_pb2.Timestamp
    def __init__(self, database: _Optional[str] = ..., database_uid: _Optional[bytes] = ..., snapshot_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
