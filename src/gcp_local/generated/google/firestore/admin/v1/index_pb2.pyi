from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Index(_message.Message):
    __slots__ = ("name", "query_scope", "api_scope", "fields", "state", "density", "multikey", "shard_count", "unique", "search_index_options")
    class QueryScope(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        QUERY_SCOPE_UNSPECIFIED: _ClassVar[Index.QueryScope]
        COLLECTION: _ClassVar[Index.QueryScope]
        COLLECTION_GROUP: _ClassVar[Index.QueryScope]
        COLLECTION_RECURSIVE: _ClassVar[Index.QueryScope]
    QUERY_SCOPE_UNSPECIFIED: Index.QueryScope
    COLLECTION: Index.QueryScope
    COLLECTION_GROUP: Index.QueryScope
    COLLECTION_RECURSIVE: Index.QueryScope
    class ApiScope(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        ANY_API: _ClassVar[Index.ApiScope]
        DATASTORE_MODE_API: _ClassVar[Index.ApiScope]
        MONGODB_COMPATIBLE_API: _ClassVar[Index.ApiScope]
    ANY_API: Index.ApiScope
    DATASTORE_MODE_API: Index.ApiScope
    MONGODB_COMPATIBLE_API: Index.ApiScope
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[Index.State]
        CREATING: _ClassVar[Index.State]
        READY: _ClassVar[Index.State]
        NEEDS_REPAIR: _ClassVar[Index.State]
    STATE_UNSPECIFIED: Index.State
    CREATING: Index.State
    READY: Index.State
    NEEDS_REPAIR: Index.State
    class Density(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        DENSITY_UNSPECIFIED: _ClassVar[Index.Density]
        SPARSE_ALL: _ClassVar[Index.Density]
        SPARSE_ANY: _ClassVar[Index.Density]
        DENSE: _ClassVar[Index.Density]
    DENSITY_UNSPECIFIED: Index.Density
    SPARSE_ALL: Index.Density
    SPARSE_ANY: Index.Density
    DENSE: Index.Density
    class IndexField(_message.Message):
        __slots__ = ("field_path", "order", "array_config", "vector_config", "search_config")
        class Order(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            ORDER_UNSPECIFIED: _ClassVar[Index.IndexField.Order]
            ASCENDING: _ClassVar[Index.IndexField.Order]
            DESCENDING: _ClassVar[Index.IndexField.Order]
        ORDER_UNSPECIFIED: Index.IndexField.Order
        ASCENDING: Index.IndexField.Order
        DESCENDING: Index.IndexField.Order
        class ArrayConfig(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            ARRAY_CONFIG_UNSPECIFIED: _ClassVar[Index.IndexField.ArrayConfig]
            CONTAINS: _ClassVar[Index.IndexField.ArrayConfig]
        ARRAY_CONFIG_UNSPECIFIED: Index.IndexField.ArrayConfig
        CONTAINS: Index.IndexField.ArrayConfig
        class VectorConfig(_message.Message):
            __slots__ = ("dimension", "flat")
            class FlatIndex(_message.Message):
                __slots__ = ()
                def __init__(self) -> None: ...
            DIMENSION_FIELD_NUMBER: _ClassVar[int]
            FLAT_FIELD_NUMBER: _ClassVar[int]
            dimension: int
            flat: Index.IndexField.VectorConfig.FlatIndex
            def __init__(self, dimension: _Optional[int] = ..., flat: _Optional[_Union[Index.IndexField.VectorConfig.FlatIndex, _Mapping]] = ...) -> None: ...
        class SearchConfig(_message.Message):
            __slots__ = ("text_spec", "geo_spec")
            class TextIndexType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = ()
                TEXT_INDEX_TYPE_UNSPECIFIED: _ClassVar[Index.IndexField.SearchConfig.TextIndexType]
                TOKENIZED: _ClassVar[Index.IndexField.SearchConfig.TextIndexType]
            TEXT_INDEX_TYPE_UNSPECIFIED: Index.IndexField.SearchConfig.TextIndexType
            TOKENIZED: Index.IndexField.SearchConfig.TextIndexType
            class TextMatchType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = ()
                TEXT_MATCH_TYPE_UNSPECIFIED: _ClassVar[Index.IndexField.SearchConfig.TextMatchType]
                MATCH_GLOBALLY: _ClassVar[Index.IndexField.SearchConfig.TextMatchType]
            TEXT_MATCH_TYPE_UNSPECIFIED: Index.IndexField.SearchConfig.TextMatchType
            MATCH_GLOBALLY: Index.IndexField.SearchConfig.TextMatchType
            class SearchTextIndexSpec(_message.Message):
                __slots__ = ("index_type", "match_type")
                INDEX_TYPE_FIELD_NUMBER: _ClassVar[int]
                MATCH_TYPE_FIELD_NUMBER: _ClassVar[int]
                index_type: Index.IndexField.SearchConfig.TextIndexType
                match_type: Index.IndexField.SearchConfig.TextMatchType
                def __init__(self, index_type: _Optional[_Union[Index.IndexField.SearchConfig.TextIndexType, str]] = ..., match_type: _Optional[_Union[Index.IndexField.SearchConfig.TextMatchType, str]] = ...) -> None: ...
            class SearchTextSpec(_message.Message):
                __slots__ = ("index_specs",)
                INDEX_SPECS_FIELD_NUMBER: _ClassVar[int]
                index_specs: _containers.RepeatedCompositeFieldContainer[Index.IndexField.SearchConfig.SearchTextIndexSpec]
                def __init__(self, index_specs: _Optional[_Iterable[_Union[Index.IndexField.SearchConfig.SearchTextIndexSpec, _Mapping]]] = ...) -> None: ...
            class SearchGeoSpec(_message.Message):
                __slots__ = ("geo_json_indexing_disabled",)
                GEO_JSON_INDEXING_DISABLED_FIELD_NUMBER: _ClassVar[int]
                geo_json_indexing_disabled: bool
                def __init__(self, geo_json_indexing_disabled: bool = ...) -> None: ...
            TEXT_SPEC_FIELD_NUMBER: _ClassVar[int]
            GEO_SPEC_FIELD_NUMBER: _ClassVar[int]
            text_spec: Index.IndexField.SearchConfig.SearchTextSpec
            geo_spec: Index.IndexField.SearchConfig.SearchGeoSpec
            def __init__(self, text_spec: _Optional[_Union[Index.IndexField.SearchConfig.SearchTextSpec, _Mapping]] = ..., geo_spec: _Optional[_Union[Index.IndexField.SearchConfig.SearchGeoSpec, _Mapping]] = ...) -> None: ...
        FIELD_PATH_FIELD_NUMBER: _ClassVar[int]
        ORDER_FIELD_NUMBER: _ClassVar[int]
        ARRAY_CONFIG_FIELD_NUMBER: _ClassVar[int]
        VECTOR_CONFIG_FIELD_NUMBER: _ClassVar[int]
        SEARCH_CONFIG_FIELD_NUMBER: _ClassVar[int]
        field_path: str
        order: Index.IndexField.Order
        array_config: Index.IndexField.ArrayConfig
        vector_config: Index.IndexField.VectorConfig
        search_config: Index.IndexField.SearchConfig
        def __init__(self, field_path: _Optional[str] = ..., order: _Optional[_Union[Index.IndexField.Order, str]] = ..., array_config: _Optional[_Union[Index.IndexField.ArrayConfig, str]] = ..., vector_config: _Optional[_Union[Index.IndexField.VectorConfig, _Mapping]] = ..., search_config: _Optional[_Union[Index.IndexField.SearchConfig, _Mapping]] = ...) -> None: ...
    class SearchIndexOptions(_message.Message):
        __slots__ = ("text_language", "text_language_override_field_path")
        TEXT_LANGUAGE_FIELD_NUMBER: _ClassVar[int]
        TEXT_LANGUAGE_OVERRIDE_FIELD_PATH_FIELD_NUMBER: _ClassVar[int]
        text_language: str
        text_language_override_field_path: str
        def __init__(self, text_language: _Optional[str] = ..., text_language_override_field_path: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    QUERY_SCOPE_FIELD_NUMBER: _ClassVar[int]
    API_SCOPE_FIELD_NUMBER: _ClassVar[int]
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    DENSITY_FIELD_NUMBER: _ClassVar[int]
    MULTIKEY_FIELD_NUMBER: _ClassVar[int]
    SHARD_COUNT_FIELD_NUMBER: _ClassVar[int]
    UNIQUE_FIELD_NUMBER: _ClassVar[int]
    SEARCH_INDEX_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    name: str
    query_scope: Index.QueryScope
    api_scope: Index.ApiScope
    fields: _containers.RepeatedCompositeFieldContainer[Index.IndexField]
    state: Index.State
    density: Index.Density
    multikey: bool
    shard_count: int
    unique: bool
    search_index_options: Index.SearchIndexOptions
    def __init__(self, name: _Optional[str] = ..., query_scope: _Optional[_Union[Index.QueryScope, str]] = ..., api_scope: _Optional[_Union[Index.ApiScope, str]] = ..., fields: _Optional[_Iterable[_Union[Index.IndexField, _Mapping]]] = ..., state: _Optional[_Union[Index.State, str]] = ..., density: _Optional[_Union[Index.Density, str]] = ..., multikey: bool = ..., shard_count: _Optional[int] = ..., unique: bool = ..., search_index_options: _Optional[_Union[Index.SearchIndexOptions, _Mapping]] = ...) -> None: ...
