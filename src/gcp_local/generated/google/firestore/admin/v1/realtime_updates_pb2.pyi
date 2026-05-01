from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from typing import ClassVar as _ClassVar

DESCRIPTOR: _descriptor.FileDescriptor

class RealtimeUpdatesMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    REALTIME_UPDATES_MODE_UNSPECIFIED: _ClassVar[RealtimeUpdatesMode]
    REALTIME_UPDATES_MODE_ENABLED: _ClassVar[RealtimeUpdatesMode]
    REALTIME_UPDATES_MODE_DISABLED: _ClassVar[RealtimeUpdatesMode]
REALTIME_UPDATES_MODE_UNSPECIFIED: RealtimeUpdatesMode
REALTIME_UPDATES_MODE_ENABLED: RealtimeUpdatesMode
REALTIME_UPDATES_MODE_DISABLED: RealtimeUpdatesMode
