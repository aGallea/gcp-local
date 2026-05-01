from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BitSequence(_message.Message):
    __slots__ = ("bitmap", "padding")
    BITMAP_FIELD_NUMBER: _ClassVar[int]
    PADDING_FIELD_NUMBER: _ClassVar[int]
    bitmap: bytes
    padding: int
    def __init__(self, bitmap: _Optional[bytes] = ..., padding: _Optional[int] = ...) -> None: ...

class BloomFilter(_message.Message):
    __slots__ = ("bits", "hash_count")
    BITS_FIELD_NUMBER: _ClassVar[int]
    HASH_COUNT_FIELD_NUMBER: _ClassVar[int]
    bits: BitSequence
    hash_count: int
    def __init__(self, bits: _Optional[_Union[BitSequence, _Mapping]] = ..., hash_count: _Optional[int] = ...) -> None: ...
