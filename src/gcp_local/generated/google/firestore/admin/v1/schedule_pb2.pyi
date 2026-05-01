import datetime

from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.type import dayofweek_pb2 as _dayofweek_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BackupSchedule(_message.Message):
    __slots__ = ("name", "create_time", "update_time", "retention", "daily_recurrence", "weekly_recurrence")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    RETENTION_FIELD_NUMBER: _ClassVar[int]
    DAILY_RECURRENCE_FIELD_NUMBER: _ClassVar[int]
    WEEKLY_RECURRENCE_FIELD_NUMBER: _ClassVar[int]
    name: str
    create_time: _timestamp_pb2.Timestamp
    update_time: _timestamp_pb2.Timestamp
    retention: _duration_pb2.Duration
    daily_recurrence: DailyRecurrence
    weekly_recurrence: WeeklyRecurrence
    def __init__(self, name: _Optional[str] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., retention: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., daily_recurrence: _Optional[_Union[DailyRecurrence, _Mapping]] = ..., weekly_recurrence: _Optional[_Union[WeeklyRecurrence, _Mapping]] = ...) -> None: ...

class DailyRecurrence(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class WeeklyRecurrence(_message.Message):
    __slots__ = ("day",)
    DAY_FIELD_NUMBER: _ClassVar[int]
    day: _dayofweek_pb2.DayOfWeek
    def __init__(self, day: _Optional[_Union[_dayofweek_pb2.DayOfWeek, str]] = ...) -> None: ...
