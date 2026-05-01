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

class UserCreds(_message.Message):
    __slots__ = ("name", "create_time", "update_time", "state", "secure_password", "resource_identity")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[UserCreds.State]
        ENABLED: _ClassVar[UserCreds.State]
        DISABLED: _ClassVar[UserCreds.State]
    STATE_UNSPECIFIED: UserCreds.State
    ENABLED: UserCreds.State
    DISABLED: UserCreds.State
    class ResourceIdentity(_message.Message):
        __slots__ = ("principal",)
        PRINCIPAL_FIELD_NUMBER: _ClassVar[int]
        principal: str
        def __init__(self, principal: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    SECURE_PASSWORD_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_IDENTITY_FIELD_NUMBER: _ClassVar[int]
    name: str
    create_time: _timestamp_pb2.Timestamp
    update_time: _timestamp_pb2.Timestamp
    state: UserCreds.State
    secure_password: str
    resource_identity: UserCreds.ResourceIdentity
    def __init__(self, name: _Optional[str] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., state: _Optional[_Union[UserCreds.State, str]] = ..., secure_password: _Optional[str] = ..., resource_identity: _Optional[_Union[UserCreds.ResourceIdentity, _Mapping]] = ...) -> None: ...
