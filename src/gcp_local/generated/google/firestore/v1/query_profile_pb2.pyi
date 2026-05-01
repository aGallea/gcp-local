import datetime

from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ExplainOptions(_message.Message):
    __slots__ = ("analyze",)
    ANALYZE_FIELD_NUMBER: _ClassVar[int]
    analyze: bool
    def __init__(self, analyze: bool = ...) -> None: ...

class ExplainMetrics(_message.Message):
    __slots__ = ("plan_summary", "execution_stats")
    PLAN_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_STATS_FIELD_NUMBER: _ClassVar[int]
    plan_summary: PlanSummary
    execution_stats: ExecutionStats
    def __init__(self, plan_summary: _Optional[_Union[PlanSummary, _Mapping]] = ..., execution_stats: _Optional[_Union[ExecutionStats, _Mapping]] = ...) -> None: ...

class PlanSummary(_message.Message):
    __slots__ = ("indexes_used",)
    INDEXES_USED_FIELD_NUMBER: _ClassVar[int]
    indexes_used: _containers.RepeatedCompositeFieldContainer[_struct_pb2.Struct]
    def __init__(self, indexes_used: _Optional[_Iterable[_Union[_struct_pb2.Struct, _Mapping]]] = ...) -> None: ...

class ExecutionStats(_message.Message):
    __slots__ = ("results_returned", "execution_duration", "read_operations", "debug_stats")
    RESULTS_RETURNED_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_DURATION_FIELD_NUMBER: _ClassVar[int]
    READ_OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    DEBUG_STATS_FIELD_NUMBER: _ClassVar[int]
    results_returned: int
    execution_duration: _duration_pb2.Duration
    read_operations: int
    debug_stats: _struct_pb2.Struct
    def __init__(self, results_returned: _Optional[int] = ..., execution_duration: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., read_operations: _Optional[int] = ..., debug_stats: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...
