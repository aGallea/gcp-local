import datetime

from google.api import annotations_pb2 as _annotations_pb2
from google.api import client_pb2 as _client_pb2
from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SchemaView(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SCHEMA_VIEW_UNSPECIFIED: _ClassVar[SchemaView]
    BASIC: _ClassVar[SchemaView]
    FULL: _ClassVar[SchemaView]

class Encoding(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENCODING_UNSPECIFIED: _ClassVar[Encoding]
    JSON: _ClassVar[Encoding]
    BINARY: _ClassVar[Encoding]
SCHEMA_VIEW_UNSPECIFIED: SchemaView
BASIC: SchemaView
FULL: SchemaView
ENCODING_UNSPECIFIED: Encoding
JSON: Encoding
BINARY: Encoding

class Schema(_message.Message):
    __slots__ = ("name", "type", "definition", "revision_id", "revision_create_time")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TYPE_UNSPECIFIED: _ClassVar[Schema.Type]
        PROTOCOL_BUFFER: _ClassVar[Schema.Type]
        AVRO: _ClassVar[Schema.Type]
    TYPE_UNSPECIFIED: Schema.Type
    PROTOCOL_BUFFER: Schema.Type
    AVRO: Schema.Type
    NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_FIELD_NUMBER: _ClassVar[int]
    REVISION_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    type: Schema.Type
    definition: str
    revision_id: str
    revision_create_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., type: _Optional[_Union[Schema.Type, str]] = ..., definition: _Optional[str] = ..., revision_id: _Optional[str] = ..., revision_create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class CreateSchemaRequest(_message.Message):
    __slots__ = ("parent", "schema", "schema_id")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_ID_FIELD_NUMBER: _ClassVar[int]
    parent: str
    schema: Schema
    schema_id: str
    def __init__(self, parent: _Optional[str] = ..., schema: _Optional[_Union[Schema, _Mapping]] = ..., schema_id: _Optional[str] = ...) -> None: ...

class GetSchemaRequest(_message.Message):
    __slots__ = ("name", "view")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VIEW_FIELD_NUMBER: _ClassVar[int]
    name: str
    view: SchemaView
    def __init__(self, name: _Optional[str] = ..., view: _Optional[_Union[SchemaView, str]] = ...) -> None: ...

class ListSchemasRequest(_message.Message):
    __slots__ = ("parent", "view", "page_size", "page_token")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    VIEW_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    parent: str
    view: SchemaView
    page_size: int
    page_token: str
    def __init__(self, parent: _Optional[str] = ..., view: _Optional[_Union[SchemaView, str]] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListSchemasResponse(_message.Message):
    __slots__ = ("schemas", "next_page_token")
    SCHEMAS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    schemas: _containers.RepeatedCompositeFieldContainer[Schema]
    next_page_token: str
    def __init__(self, schemas: _Optional[_Iterable[_Union[Schema, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class ListSchemaRevisionsRequest(_message.Message):
    __slots__ = ("name", "view", "page_size", "page_token")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VIEW_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    name: str
    view: SchemaView
    page_size: int
    page_token: str
    def __init__(self, name: _Optional[str] = ..., view: _Optional[_Union[SchemaView, str]] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListSchemaRevisionsResponse(_message.Message):
    __slots__ = ("schemas", "next_page_token")
    SCHEMAS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    schemas: _containers.RepeatedCompositeFieldContainer[Schema]
    next_page_token: str
    def __init__(self, schemas: _Optional[_Iterable[_Union[Schema, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class CommitSchemaRequest(_message.Message):
    __slots__ = ("name", "schema")
    NAME_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    name: str
    schema: Schema
    def __init__(self, name: _Optional[str] = ..., schema: _Optional[_Union[Schema, _Mapping]] = ...) -> None: ...

class RollbackSchemaRequest(_message.Message):
    __slots__ = ("name", "revision_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    REVISION_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    revision_id: str
    def __init__(self, name: _Optional[str] = ..., revision_id: _Optional[str] = ...) -> None: ...

class DeleteSchemaRevisionRequest(_message.Message):
    __slots__ = ("name", "revision_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    REVISION_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    revision_id: str
    def __init__(self, name: _Optional[str] = ..., revision_id: _Optional[str] = ...) -> None: ...

class DeleteSchemaRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ValidateSchemaRequest(_message.Message):
    __slots__ = ("parent", "schema")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    parent: str
    schema: Schema
    def __init__(self, parent: _Optional[str] = ..., schema: _Optional[_Union[Schema, _Mapping]] = ...) -> None: ...

class ValidateSchemaResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ValidateMessageRequest(_message.Message):
    __slots__ = ("parent", "name", "schema", "message", "encoding")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ENCODING_FIELD_NUMBER: _ClassVar[int]
    parent: str
    name: str
    schema: Schema
    message: bytes
    encoding: Encoding
    def __init__(self, parent: _Optional[str] = ..., name: _Optional[str] = ..., schema: _Optional[_Union[Schema, _Mapping]] = ..., message: _Optional[bytes] = ..., encoding: _Optional[_Union[Encoding, str]] = ...) -> None: ...

class ValidateMessageResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
