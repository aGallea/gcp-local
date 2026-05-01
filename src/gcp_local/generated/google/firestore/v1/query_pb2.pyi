from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.firestore.v1 import document_pb2 as _document_pb2
from google.protobuf import wrappers_pb2 as _wrappers_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StructuredQuery(_message.Message):
    __slots__ = ("select", "where", "order_by", "start_at", "end_at", "offset", "limit", "find_nearest")
    class Direction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        DIRECTION_UNSPECIFIED: _ClassVar[StructuredQuery.Direction]
        ASCENDING: _ClassVar[StructuredQuery.Direction]
        DESCENDING: _ClassVar[StructuredQuery.Direction]
    DIRECTION_UNSPECIFIED: StructuredQuery.Direction
    ASCENDING: StructuredQuery.Direction
    DESCENDING: StructuredQuery.Direction
    class CollectionSelector(_message.Message):
        __slots__ = ("collection_id", "all_descendants")
        COLLECTION_ID_FIELD_NUMBER: _ClassVar[int]
        ALL_DESCENDANTS_FIELD_NUMBER: _ClassVar[int]
        collection_id: str
        all_descendants: bool
        def __init__(self, collection_id: _Optional[str] = ..., all_descendants: bool = ...) -> None: ...
    class Filter(_message.Message):
        __slots__ = ("composite_filter", "field_filter", "unary_filter")
        COMPOSITE_FILTER_FIELD_NUMBER: _ClassVar[int]
        FIELD_FILTER_FIELD_NUMBER: _ClassVar[int]
        UNARY_FILTER_FIELD_NUMBER: _ClassVar[int]
        composite_filter: StructuredQuery.CompositeFilter
        field_filter: StructuredQuery.FieldFilter
        unary_filter: StructuredQuery.UnaryFilter
        def __init__(self, composite_filter: _Optional[_Union[StructuredQuery.CompositeFilter, _Mapping]] = ..., field_filter: _Optional[_Union[StructuredQuery.FieldFilter, _Mapping]] = ..., unary_filter: _Optional[_Union[StructuredQuery.UnaryFilter, _Mapping]] = ...) -> None: ...
    class CompositeFilter(_message.Message):
        __slots__ = ("op", "filters")
        class Operator(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            OPERATOR_UNSPECIFIED: _ClassVar[StructuredQuery.CompositeFilter.Operator]
            AND: _ClassVar[StructuredQuery.CompositeFilter.Operator]
            OR: _ClassVar[StructuredQuery.CompositeFilter.Operator]
        OPERATOR_UNSPECIFIED: StructuredQuery.CompositeFilter.Operator
        AND: StructuredQuery.CompositeFilter.Operator
        OR: StructuredQuery.CompositeFilter.Operator
        OP_FIELD_NUMBER: _ClassVar[int]
        FILTERS_FIELD_NUMBER: _ClassVar[int]
        op: StructuredQuery.CompositeFilter.Operator
        filters: _containers.RepeatedCompositeFieldContainer[StructuredQuery.Filter]
        def __init__(self, op: _Optional[_Union[StructuredQuery.CompositeFilter.Operator, str]] = ..., filters: _Optional[_Iterable[_Union[StructuredQuery.Filter, _Mapping]]] = ...) -> None: ...
    class FieldFilter(_message.Message):
        __slots__ = ("field", "op", "value")
        class Operator(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            OPERATOR_UNSPECIFIED: _ClassVar[StructuredQuery.FieldFilter.Operator]
            LESS_THAN: _ClassVar[StructuredQuery.FieldFilter.Operator]
            LESS_THAN_OR_EQUAL: _ClassVar[StructuredQuery.FieldFilter.Operator]
            GREATER_THAN: _ClassVar[StructuredQuery.FieldFilter.Operator]
            GREATER_THAN_OR_EQUAL: _ClassVar[StructuredQuery.FieldFilter.Operator]
            EQUAL: _ClassVar[StructuredQuery.FieldFilter.Operator]
            NOT_EQUAL: _ClassVar[StructuredQuery.FieldFilter.Operator]
            ARRAY_CONTAINS: _ClassVar[StructuredQuery.FieldFilter.Operator]
            IN: _ClassVar[StructuredQuery.FieldFilter.Operator]
            ARRAY_CONTAINS_ANY: _ClassVar[StructuredQuery.FieldFilter.Operator]
            NOT_IN: _ClassVar[StructuredQuery.FieldFilter.Operator]
        OPERATOR_UNSPECIFIED: StructuredQuery.FieldFilter.Operator
        LESS_THAN: StructuredQuery.FieldFilter.Operator
        LESS_THAN_OR_EQUAL: StructuredQuery.FieldFilter.Operator
        GREATER_THAN: StructuredQuery.FieldFilter.Operator
        GREATER_THAN_OR_EQUAL: StructuredQuery.FieldFilter.Operator
        EQUAL: StructuredQuery.FieldFilter.Operator
        NOT_EQUAL: StructuredQuery.FieldFilter.Operator
        ARRAY_CONTAINS: StructuredQuery.FieldFilter.Operator
        IN: StructuredQuery.FieldFilter.Operator
        ARRAY_CONTAINS_ANY: StructuredQuery.FieldFilter.Operator
        NOT_IN: StructuredQuery.FieldFilter.Operator
        FIELD_FIELD_NUMBER: _ClassVar[int]
        OP_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        field: StructuredQuery.FieldReference
        op: StructuredQuery.FieldFilter.Operator
        value: _document_pb2.Value
        def __init__(self, field: _Optional[_Union[StructuredQuery.FieldReference, _Mapping]] = ..., op: _Optional[_Union[StructuredQuery.FieldFilter.Operator, str]] = ..., value: _Optional[_Union[_document_pb2.Value, _Mapping]] = ...) -> None: ...
    class UnaryFilter(_message.Message):
        __slots__ = ("op", "field")
        class Operator(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            OPERATOR_UNSPECIFIED: _ClassVar[StructuredQuery.UnaryFilter.Operator]
            IS_NAN: _ClassVar[StructuredQuery.UnaryFilter.Operator]
            IS_NULL: _ClassVar[StructuredQuery.UnaryFilter.Operator]
            IS_NOT_NAN: _ClassVar[StructuredQuery.UnaryFilter.Operator]
            IS_NOT_NULL: _ClassVar[StructuredQuery.UnaryFilter.Operator]
        OPERATOR_UNSPECIFIED: StructuredQuery.UnaryFilter.Operator
        IS_NAN: StructuredQuery.UnaryFilter.Operator
        IS_NULL: StructuredQuery.UnaryFilter.Operator
        IS_NOT_NAN: StructuredQuery.UnaryFilter.Operator
        IS_NOT_NULL: StructuredQuery.UnaryFilter.Operator
        OP_FIELD_NUMBER: _ClassVar[int]
        FIELD_FIELD_NUMBER: _ClassVar[int]
        op: StructuredQuery.UnaryFilter.Operator
        field: StructuredQuery.FieldReference
        def __init__(self, op: _Optional[_Union[StructuredQuery.UnaryFilter.Operator, str]] = ..., field: _Optional[_Union[StructuredQuery.FieldReference, _Mapping]] = ...) -> None: ...
    class Order(_message.Message):
        __slots__ = ("field", "direction")
        FIELD_FIELD_NUMBER: _ClassVar[int]
        DIRECTION_FIELD_NUMBER: _ClassVar[int]
        field: StructuredQuery.FieldReference
        direction: StructuredQuery.Direction
        def __init__(self, field: _Optional[_Union[StructuredQuery.FieldReference, _Mapping]] = ..., direction: _Optional[_Union[StructuredQuery.Direction, str]] = ...) -> None: ...
    class FieldReference(_message.Message):
        __slots__ = ("field_path",)
        FIELD_PATH_FIELD_NUMBER: _ClassVar[int]
        field_path: str
        def __init__(self, field_path: _Optional[str] = ...) -> None: ...
    class Projection(_message.Message):
        __slots__ = ("fields",)
        FIELDS_FIELD_NUMBER: _ClassVar[int]
        fields: _containers.RepeatedCompositeFieldContainer[StructuredQuery.FieldReference]
        def __init__(self, fields: _Optional[_Iterable[_Union[StructuredQuery.FieldReference, _Mapping]]] = ...) -> None: ...
    class FindNearest(_message.Message):
        __slots__ = ("vector_field", "query_vector", "distance_measure", "limit", "distance_result_field", "distance_threshold")
        class DistanceMeasure(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            DISTANCE_MEASURE_UNSPECIFIED: _ClassVar[StructuredQuery.FindNearest.DistanceMeasure]
            EUCLIDEAN: _ClassVar[StructuredQuery.FindNearest.DistanceMeasure]
            COSINE: _ClassVar[StructuredQuery.FindNearest.DistanceMeasure]
            DOT_PRODUCT: _ClassVar[StructuredQuery.FindNearest.DistanceMeasure]
        DISTANCE_MEASURE_UNSPECIFIED: StructuredQuery.FindNearest.DistanceMeasure
        EUCLIDEAN: StructuredQuery.FindNearest.DistanceMeasure
        COSINE: StructuredQuery.FindNearest.DistanceMeasure
        DOT_PRODUCT: StructuredQuery.FindNearest.DistanceMeasure
        VECTOR_FIELD_FIELD_NUMBER: _ClassVar[int]
        QUERY_VECTOR_FIELD_NUMBER: _ClassVar[int]
        DISTANCE_MEASURE_FIELD_NUMBER: _ClassVar[int]
        LIMIT_FIELD_NUMBER: _ClassVar[int]
        DISTANCE_RESULT_FIELD_FIELD_NUMBER: _ClassVar[int]
        DISTANCE_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
        vector_field: StructuredQuery.FieldReference
        query_vector: _document_pb2.Value
        distance_measure: StructuredQuery.FindNearest.DistanceMeasure
        limit: _wrappers_pb2.Int32Value
        distance_result_field: str
        distance_threshold: _wrappers_pb2.DoubleValue
        def __init__(self, vector_field: _Optional[_Union[StructuredQuery.FieldReference, _Mapping]] = ..., query_vector: _Optional[_Union[_document_pb2.Value, _Mapping]] = ..., distance_measure: _Optional[_Union[StructuredQuery.FindNearest.DistanceMeasure, str]] = ..., limit: _Optional[_Union[_wrappers_pb2.Int32Value, _Mapping]] = ..., distance_result_field: _Optional[str] = ..., distance_threshold: _Optional[_Union[_wrappers_pb2.DoubleValue, _Mapping]] = ...) -> None: ...
    SELECT_FIELD_NUMBER: _ClassVar[int]
    FROM_FIELD_NUMBER: _ClassVar[int]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    START_AT_FIELD_NUMBER: _ClassVar[int]
    END_AT_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    FIND_NEAREST_FIELD_NUMBER: _ClassVar[int]
    select: StructuredQuery.Projection
    where: StructuredQuery.Filter
    order_by: _containers.RepeatedCompositeFieldContainer[StructuredQuery.Order]
    start_at: Cursor
    end_at: Cursor
    offset: int
    limit: _wrappers_pb2.Int32Value
    find_nearest: StructuredQuery.FindNearest
    def __init__(self, select: _Optional[_Union[StructuredQuery.Projection, _Mapping]] = ..., where: _Optional[_Union[StructuredQuery.Filter, _Mapping]] = ..., order_by: _Optional[_Iterable[_Union[StructuredQuery.Order, _Mapping]]] = ..., start_at: _Optional[_Union[Cursor, _Mapping]] = ..., end_at: _Optional[_Union[Cursor, _Mapping]] = ..., offset: _Optional[int] = ..., limit: _Optional[_Union[_wrappers_pb2.Int32Value, _Mapping]] = ..., find_nearest: _Optional[_Union[StructuredQuery.FindNearest, _Mapping]] = ..., **kwargs) -> None: ...

class StructuredAggregationQuery(_message.Message):
    __slots__ = ("structured_query", "aggregations")
    class Aggregation(_message.Message):
        __slots__ = ("count", "sum", "avg", "alias")
        class Count(_message.Message):
            __slots__ = ("up_to",)
            UP_TO_FIELD_NUMBER: _ClassVar[int]
            up_to: _wrappers_pb2.Int64Value
            def __init__(self, up_to: _Optional[_Union[_wrappers_pb2.Int64Value, _Mapping]] = ...) -> None: ...
        class Sum(_message.Message):
            __slots__ = ("field",)
            FIELD_FIELD_NUMBER: _ClassVar[int]
            field: StructuredQuery.FieldReference
            def __init__(self, field: _Optional[_Union[StructuredQuery.FieldReference, _Mapping]] = ...) -> None: ...
        class Avg(_message.Message):
            __slots__ = ("field",)
            FIELD_FIELD_NUMBER: _ClassVar[int]
            field: StructuredQuery.FieldReference
            def __init__(self, field: _Optional[_Union[StructuredQuery.FieldReference, _Mapping]] = ...) -> None: ...
        COUNT_FIELD_NUMBER: _ClassVar[int]
        SUM_FIELD_NUMBER: _ClassVar[int]
        AVG_FIELD_NUMBER: _ClassVar[int]
        ALIAS_FIELD_NUMBER: _ClassVar[int]
        count: StructuredAggregationQuery.Aggregation.Count
        sum: StructuredAggregationQuery.Aggregation.Sum
        avg: StructuredAggregationQuery.Aggregation.Avg
        alias: str
        def __init__(self, count: _Optional[_Union[StructuredAggregationQuery.Aggregation.Count, _Mapping]] = ..., sum: _Optional[_Union[StructuredAggregationQuery.Aggregation.Sum, _Mapping]] = ..., avg: _Optional[_Union[StructuredAggregationQuery.Aggregation.Avg, _Mapping]] = ..., alias: _Optional[str] = ...) -> None: ...
    STRUCTURED_QUERY_FIELD_NUMBER: _ClassVar[int]
    AGGREGATIONS_FIELD_NUMBER: _ClassVar[int]
    structured_query: StructuredQuery
    aggregations: _containers.RepeatedCompositeFieldContainer[StructuredAggregationQuery.Aggregation]
    def __init__(self, structured_query: _Optional[_Union[StructuredQuery, _Mapping]] = ..., aggregations: _Optional[_Iterable[_Union[StructuredAggregationQuery.Aggregation, _Mapping]]] = ...) -> None: ...

class Cursor(_message.Message):
    __slots__ = ("values", "before")
    VALUES_FIELD_NUMBER: _ClassVar[int]
    BEFORE_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedCompositeFieldContainer[_document_pb2.Value]
    before: bool
    def __init__(self, values: _Optional[_Iterable[_Union[_document_pb2.Value, _Mapping]]] = ..., before: bool = ...) -> None: ...
