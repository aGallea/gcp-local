import datetime

from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.firestore.admin.v1 import index_pb2 as _index_pb2
from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Field(_message.Message):
    __slots__ = ("name", "index_config", "ttl_config")
    class IndexConfig(_message.Message):
        __slots__ = ("indexes", "uses_ancestor_config", "ancestor_field", "reverting")
        INDEXES_FIELD_NUMBER: _ClassVar[int]
        USES_ANCESTOR_CONFIG_FIELD_NUMBER: _ClassVar[int]
        ANCESTOR_FIELD_FIELD_NUMBER: _ClassVar[int]
        REVERTING_FIELD_NUMBER: _ClassVar[int]
        indexes: _containers.RepeatedCompositeFieldContainer[_index_pb2.Index]
        uses_ancestor_config: bool
        ancestor_field: str
        reverting: bool
        def __init__(self, indexes: _Optional[_Iterable[_Union[_index_pb2.Index, _Mapping]]] = ..., uses_ancestor_config: bool = ..., ancestor_field: _Optional[str] = ..., reverting: bool = ...) -> None: ...
    class TtlConfig(_message.Message):
        __slots__ = ("state", "expiration_offset")
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            STATE_UNSPECIFIED: _ClassVar[Field.TtlConfig.State]
            CREATING: _ClassVar[Field.TtlConfig.State]
            ACTIVE: _ClassVar[Field.TtlConfig.State]
            NEEDS_REPAIR: _ClassVar[Field.TtlConfig.State]
        STATE_UNSPECIFIED: Field.TtlConfig.State
        CREATING: Field.TtlConfig.State
        ACTIVE: Field.TtlConfig.State
        NEEDS_REPAIR: Field.TtlConfig.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        EXPIRATION_OFFSET_FIELD_NUMBER: _ClassVar[int]
        state: Field.TtlConfig.State
        expiration_offset: _duration_pb2.Duration
        def __init__(self, state: _Optional[_Union[Field.TtlConfig.State, str]] = ..., expiration_offset: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    INDEX_CONFIG_FIELD_NUMBER: _ClassVar[int]
    TTL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    name: str
    index_config: Field.IndexConfig
    ttl_config: Field.TtlConfig
    def __init__(self, name: _Optional[str] = ..., index_config: _Optional[_Union[Field.IndexConfig, _Mapping]] = ..., ttl_config: _Optional[_Union[Field.TtlConfig, _Mapping]] = ...) -> None: ...
