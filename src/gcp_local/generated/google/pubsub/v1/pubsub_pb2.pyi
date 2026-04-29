import datetime

from google.api import annotations_pb2 as _annotations_pb2
from google.api import client_pb2 as _client_pb2
from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import field_mask_pb2 as _field_mask_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.pubsub.v1 import schema_pb2 as _schema_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class MessageStoragePolicy(_message.Message):
    __slots__ = ("allowed_persistence_regions", "enforce_in_transit")
    ALLOWED_PERSISTENCE_REGIONS_FIELD_NUMBER: _ClassVar[int]
    ENFORCE_IN_TRANSIT_FIELD_NUMBER: _ClassVar[int]
    allowed_persistence_regions: _containers.RepeatedScalarFieldContainer[str]
    enforce_in_transit: bool
    def __init__(self, allowed_persistence_regions: _Optional[_Iterable[str]] = ..., enforce_in_transit: bool = ...) -> None: ...

class SchemaSettings(_message.Message):
    __slots__ = ("schema", "encoding", "first_revision_id", "last_revision_id")
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    ENCODING_FIELD_NUMBER: _ClassVar[int]
    FIRST_REVISION_ID_FIELD_NUMBER: _ClassVar[int]
    LAST_REVISION_ID_FIELD_NUMBER: _ClassVar[int]
    schema: str
    encoding: _schema_pb2.Encoding
    first_revision_id: str
    last_revision_id: str
    def __init__(self, schema: _Optional[str] = ..., encoding: _Optional[_Union[_schema_pb2.Encoding, str]] = ..., first_revision_id: _Optional[str] = ..., last_revision_id: _Optional[str] = ...) -> None: ...

class IngestionDataSourceSettings(_message.Message):
    __slots__ = ("aws_kinesis", "cloud_storage", "azure_event_hubs", "aws_msk", "confluent_cloud", "platform_logs_settings")
    class AwsKinesis(_message.Message):
        __slots__ = ("state", "stream_arn", "consumer_arn", "aws_role_arn", "gcp_service_account")
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            STATE_UNSPECIFIED: _ClassVar[IngestionDataSourceSettings.AwsKinesis.State]
            ACTIVE: _ClassVar[IngestionDataSourceSettings.AwsKinesis.State]
            KINESIS_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.AwsKinesis.State]
            PUBLISH_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.AwsKinesis.State]
            STREAM_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AwsKinesis.State]
            CONSUMER_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AwsKinesis.State]
        STATE_UNSPECIFIED: IngestionDataSourceSettings.AwsKinesis.State
        ACTIVE: IngestionDataSourceSettings.AwsKinesis.State
        KINESIS_PERMISSION_DENIED: IngestionDataSourceSettings.AwsKinesis.State
        PUBLISH_PERMISSION_DENIED: IngestionDataSourceSettings.AwsKinesis.State
        STREAM_NOT_FOUND: IngestionDataSourceSettings.AwsKinesis.State
        CONSUMER_NOT_FOUND: IngestionDataSourceSettings.AwsKinesis.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        STREAM_ARN_FIELD_NUMBER: _ClassVar[int]
        CONSUMER_ARN_FIELD_NUMBER: _ClassVar[int]
        AWS_ROLE_ARN_FIELD_NUMBER: _ClassVar[int]
        GCP_SERVICE_ACCOUNT_FIELD_NUMBER: _ClassVar[int]
        state: IngestionDataSourceSettings.AwsKinesis.State
        stream_arn: str
        consumer_arn: str
        aws_role_arn: str
        gcp_service_account: str
        def __init__(self, state: _Optional[_Union[IngestionDataSourceSettings.AwsKinesis.State, str]] = ..., stream_arn: _Optional[str] = ..., consumer_arn: _Optional[str] = ..., aws_role_arn: _Optional[str] = ..., gcp_service_account: _Optional[str] = ...) -> None: ...
    class CloudStorage(_message.Message):
        __slots__ = ("state", "bucket", "text_format", "avro_format", "pubsub_avro_format", "minimum_object_create_time", "match_glob")
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            STATE_UNSPECIFIED: _ClassVar[IngestionDataSourceSettings.CloudStorage.State]
            ACTIVE: _ClassVar[IngestionDataSourceSettings.CloudStorage.State]
            CLOUD_STORAGE_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.CloudStorage.State]
            PUBLISH_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.CloudStorage.State]
            BUCKET_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.CloudStorage.State]
            TOO_MANY_OBJECTS: _ClassVar[IngestionDataSourceSettings.CloudStorage.State]
        STATE_UNSPECIFIED: IngestionDataSourceSettings.CloudStorage.State
        ACTIVE: IngestionDataSourceSettings.CloudStorage.State
        CLOUD_STORAGE_PERMISSION_DENIED: IngestionDataSourceSettings.CloudStorage.State
        PUBLISH_PERMISSION_DENIED: IngestionDataSourceSettings.CloudStorage.State
        BUCKET_NOT_FOUND: IngestionDataSourceSettings.CloudStorage.State
        TOO_MANY_OBJECTS: IngestionDataSourceSettings.CloudStorage.State
        class TextFormat(_message.Message):
            __slots__ = ("delimiter",)
            DELIMITER_FIELD_NUMBER: _ClassVar[int]
            delimiter: str
            def __init__(self, delimiter: _Optional[str] = ...) -> None: ...
        class AvroFormat(_message.Message):
            __slots__ = ()
            def __init__(self) -> None: ...
        class PubSubAvroFormat(_message.Message):
            __slots__ = ()
            def __init__(self) -> None: ...
        STATE_FIELD_NUMBER: _ClassVar[int]
        BUCKET_FIELD_NUMBER: _ClassVar[int]
        TEXT_FORMAT_FIELD_NUMBER: _ClassVar[int]
        AVRO_FORMAT_FIELD_NUMBER: _ClassVar[int]
        PUBSUB_AVRO_FORMAT_FIELD_NUMBER: _ClassVar[int]
        MINIMUM_OBJECT_CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
        MATCH_GLOB_FIELD_NUMBER: _ClassVar[int]
        state: IngestionDataSourceSettings.CloudStorage.State
        bucket: str
        text_format: IngestionDataSourceSettings.CloudStorage.TextFormat
        avro_format: IngestionDataSourceSettings.CloudStorage.AvroFormat
        pubsub_avro_format: IngestionDataSourceSettings.CloudStorage.PubSubAvroFormat
        minimum_object_create_time: _timestamp_pb2.Timestamp
        match_glob: str
        def __init__(self, state: _Optional[_Union[IngestionDataSourceSettings.CloudStorage.State, str]] = ..., bucket: _Optional[str] = ..., text_format: _Optional[_Union[IngestionDataSourceSettings.CloudStorage.TextFormat, _Mapping]] = ..., avro_format: _Optional[_Union[IngestionDataSourceSettings.CloudStorage.AvroFormat, _Mapping]] = ..., pubsub_avro_format: _Optional[_Union[IngestionDataSourceSettings.CloudStorage.PubSubAvroFormat, _Mapping]] = ..., minimum_object_create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., match_glob: _Optional[str] = ...) -> None: ...
    class AzureEventHubs(_message.Message):
        __slots__ = ("state", "resource_group", "namespace", "event_hub", "client_id", "tenant_id", "subscription_id", "gcp_service_account")
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            STATE_UNSPECIFIED: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
            ACTIVE: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
            EVENT_HUBS_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
            PUBLISH_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
            NAMESPACE_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
            EVENT_HUB_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
            SUBSCRIPTION_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
            RESOURCE_GROUP_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AzureEventHubs.State]
        STATE_UNSPECIFIED: IngestionDataSourceSettings.AzureEventHubs.State
        ACTIVE: IngestionDataSourceSettings.AzureEventHubs.State
        EVENT_HUBS_PERMISSION_DENIED: IngestionDataSourceSettings.AzureEventHubs.State
        PUBLISH_PERMISSION_DENIED: IngestionDataSourceSettings.AzureEventHubs.State
        NAMESPACE_NOT_FOUND: IngestionDataSourceSettings.AzureEventHubs.State
        EVENT_HUB_NOT_FOUND: IngestionDataSourceSettings.AzureEventHubs.State
        SUBSCRIPTION_NOT_FOUND: IngestionDataSourceSettings.AzureEventHubs.State
        RESOURCE_GROUP_NOT_FOUND: IngestionDataSourceSettings.AzureEventHubs.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        RESOURCE_GROUP_FIELD_NUMBER: _ClassVar[int]
        NAMESPACE_FIELD_NUMBER: _ClassVar[int]
        EVENT_HUB_FIELD_NUMBER: _ClassVar[int]
        CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
        TENANT_ID_FIELD_NUMBER: _ClassVar[int]
        SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
        GCP_SERVICE_ACCOUNT_FIELD_NUMBER: _ClassVar[int]
        state: IngestionDataSourceSettings.AzureEventHubs.State
        resource_group: str
        namespace: str
        event_hub: str
        client_id: str
        tenant_id: str
        subscription_id: str
        gcp_service_account: str
        def __init__(self, state: _Optional[_Union[IngestionDataSourceSettings.AzureEventHubs.State, str]] = ..., resource_group: _Optional[str] = ..., namespace: _Optional[str] = ..., event_hub: _Optional[str] = ..., client_id: _Optional[str] = ..., tenant_id: _Optional[str] = ..., subscription_id: _Optional[str] = ..., gcp_service_account: _Optional[str] = ...) -> None: ...
    class AwsMsk(_message.Message):
        __slots__ = ("state", "cluster_arn", "topic", "aws_role_arn", "gcp_service_account")
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            STATE_UNSPECIFIED: _ClassVar[IngestionDataSourceSettings.AwsMsk.State]
            ACTIVE: _ClassVar[IngestionDataSourceSettings.AwsMsk.State]
            MSK_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.AwsMsk.State]
            PUBLISH_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.AwsMsk.State]
            CLUSTER_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AwsMsk.State]
            TOPIC_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.AwsMsk.State]
        STATE_UNSPECIFIED: IngestionDataSourceSettings.AwsMsk.State
        ACTIVE: IngestionDataSourceSettings.AwsMsk.State
        MSK_PERMISSION_DENIED: IngestionDataSourceSettings.AwsMsk.State
        PUBLISH_PERMISSION_DENIED: IngestionDataSourceSettings.AwsMsk.State
        CLUSTER_NOT_FOUND: IngestionDataSourceSettings.AwsMsk.State
        TOPIC_NOT_FOUND: IngestionDataSourceSettings.AwsMsk.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        CLUSTER_ARN_FIELD_NUMBER: _ClassVar[int]
        TOPIC_FIELD_NUMBER: _ClassVar[int]
        AWS_ROLE_ARN_FIELD_NUMBER: _ClassVar[int]
        GCP_SERVICE_ACCOUNT_FIELD_NUMBER: _ClassVar[int]
        state: IngestionDataSourceSettings.AwsMsk.State
        cluster_arn: str
        topic: str
        aws_role_arn: str
        gcp_service_account: str
        def __init__(self, state: _Optional[_Union[IngestionDataSourceSettings.AwsMsk.State, str]] = ..., cluster_arn: _Optional[str] = ..., topic: _Optional[str] = ..., aws_role_arn: _Optional[str] = ..., gcp_service_account: _Optional[str] = ...) -> None: ...
    class ConfluentCloud(_message.Message):
        __slots__ = ("state", "bootstrap_server", "cluster_id", "topic", "identity_pool_id", "gcp_service_account")
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            STATE_UNSPECIFIED: _ClassVar[IngestionDataSourceSettings.ConfluentCloud.State]
            ACTIVE: _ClassVar[IngestionDataSourceSettings.ConfluentCloud.State]
            CONFLUENT_CLOUD_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.ConfluentCloud.State]
            PUBLISH_PERMISSION_DENIED: _ClassVar[IngestionDataSourceSettings.ConfluentCloud.State]
            UNREACHABLE_BOOTSTRAP_SERVER: _ClassVar[IngestionDataSourceSettings.ConfluentCloud.State]
            CLUSTER_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.ConfluentCloud.State]
            TOPIC_NOT_FOUND: _ClassVar[IngestionDataSourceSettings.ConfluentCloud.State]
        STATE_UNSPECIFIED: IngestionDataSourceSettings.ConfluentCloud.State
        ACTIVE: IngestionDataSourceSettings.ConfluentCloud.State
        CONFLUENT_CLOUD_PERMISSION_DENIED: IngestionDataSourceSettings.ConfluentCloud.State
        PUBLISH_PERMISSION_DENIED: IngestionDataSourceSettings.ConfluentCloud.State
        UNREACHABLE_BOOTSTRAP_SERVER: IngestionDataSourceSettings.ConfluentCloud.State
        CLUSTER_NOT_FOUND: IngestionDataSourceSettings.ConfluentCloud.State
        TOPIC_NOT_FOUND: IngestionDataSourceSettings.ConfluentCloud.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        BOOTSTRAP_SERVER_FIELD_NUMBER: _ClassVar[int]
        CLUSTER_ID_FIELD_NUMBER: _ClassVar[int]
        TOPIC_FIELD_NUMBER: _ClassVar[int]
        IDENTITY_POOL_ID_FIELD_NUMBER: _ClassVar[int]
        GCP_SERVICE_ACCOUNT_FIELD_NUMBER: _ClassVar[int]
        state: IngestionDataSourceSettings.ConfluentCloud.State
        bootstrap_server: str
        cluster_id: str
        topic: str
        identity_pool_id: str
        gcp_service_account: str
        def __init__(self, state: _Optional[_Union[IngestionDataSourceSettings.ConfluentCloud.State, str]] = ..., bootstrap_server: _Optional[str] = ..., cluster_id: _Optional[str] = ..., topic: _Optional[str] = ..., identity_pool_id: _Optional[str] = ..., gcp_service_account: _Optional[str] = ...) -> None: ...
    AWS_KINESIS_FIELD_NUMBER: _ClassVar[int]
    CLOUD_STORAGE_FIELD_NUMBER: _ClassVar[int]
    AZURE_EVENT_HUBS_FIELD_NUMBER: _ClassVar[int]
    AWS_MSK_FIELD_NUMBER: _ClassVar[int]
    CONFLUENT_CLOUD_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_LOGS_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    aws_kinesis: IngestionDataSourceSettings.AwsKinesis
    cloud_storage: IngestionDataSourceSettings.CloudStorage
    azure_event_hubs: IngestionDataSourceSettings.AzureEventHubs
    aws_msk: IngestionDataSourceSettings.AwsMsk
    confluent_cloud: IngestionDataSourceSettings.ConfluentCloud
    platform_logs_settings: PlatformLogsSettings
    def __init__(self, aws_kinesis: _Optional[_Union[IngestionDataSourceSettings.AwsKinesis, _Mapping]] = ..., cloud_storage: _Optional[_Union[IngestionDataSourceSettings.CloudStorage, _Mapping]] = ..., azure_event_hubs: _Optional[_Union[IngestionDataSourceSettings.AzureEventHubs, _Mapping]] = ..., aws_msk: _Optional[_Union[IngestionDataSourceSettings.AwsMsk, _Mapping]] = ..., confluent_cloud: _Optional[_Union[IngestionDataSourceSettings.ConfluentCloud, _Mapping]] = ..., platform_logs_settings: _Optional[_Union[PlatformLogsSettings, _Mapping]] = ...) -> None: ...

class PlatformLogsSettings(_message.Message):
    __slots__ = ("severity",)
    class Severity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SEVERITY_UNSPECIFIED: _ClassVar[PlatformLogsSettings.Severity]
        DISABLED: _ClassVar[PlatformLogsSettings.Severity]
        DEBUG: _ClassVar[PlatformLogsSettings.Severity]
        INFO: _ClassVar[PlatformLogsSettings.Severity]
        WARNING: _ClassVar[PlatformLogsSettings.Severity]
        ERROR: _ClassVar[PlatformLogsSettings.Severity]
    SEVERITY_UNSPECIFIED: PlatformLogsSettings.Severity
    DISABLED: PlatformLogsSettings.Severity
    DEBUG: PlatformLogsSettings.Severity
    INFO: PlatformLogsSettings.Severity
    WARNING: PlatformLogsSettings.Severity
    ERROR: PlatformLogsSettings.Severity
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    severity: PlatformLogsSettings.Severity
    def __init__(self, severity: _Optional[_Union[PlatformLogsSettings.Severity, str]] = ...) -> None: ...

class IngestionFailureEvent(_message.Message):
    __slots__ = ("topic", "error_message", "cloud_storage_failure", "aws_msk_failure", "azure_event_hubs_failure", "confluent_cloud_failure", "aws_kinesis_failure")
    class ApiViolationReason(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class AvroFailureReason(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class SchemaViolationReason(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class MessageTransformationFailureReason(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class CloudStorageFailure(_message.Message):
        __slots__ = ("bucket", "object_name", "object_generation", "avro_failure_reason", "api_violation_reason", "schema_violation_reason", "message_transformation_failure_reason")
        BUCKET_FIELD_NUMBER: _ClassVar[int]
        OBJECT_NAME_FIELD_NUMBER: _ClassVar[int]
        OBJECT_GENERATION_FIELD_NUMBER: _ClassVar[int]
        AVRO_FAILURE_REASON_FIELD_NUMBER: _ClassVar[int]
        API_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        SCHEMA_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        MESSAGE_TRANSFORMATION_FAILURE_REASON_FIELD_NUMBER: _ClassVar[int]
        bucket: str
        object_name: str
        object_generation: int
        avro_failure_reason: IngestionFailureEvent.AvroFailureReason
        api_violation_reason: IngestionFailureEvent.ApiViolationReason
        schema_violation_reason: IngestionFailureEvent.SchemaViolationReason
        message_transformation_failure_reason: IngestionFailureEvent.MessageTransformationFailureReason
        def __init__(self, bucket: _Optional[str] = ..., object_name: _Optional[str] = ..., object_generation: _Optional[int] = ..., avro_failure_reason: _Optional[_Union[IngestionFailureEvent.AvroFailureReason, _Mapping]] = ..., api_violation_reason: _Optional[_Union[IngestionFailureEvent.ApiViolationReason, _Mapping]] = ..., schema_violation_reason: _Optional[_Union[IngestionFailureEvent.SchemaViolationReason, _Mapping]] = ..., message_transformation_failure_reason: _Optional[_Union[IngestionFailureEvent.MessageTransformationFailureReason, _Mapping]] = ...) -> None: ...
    class AwsMskFailureReason(_message.Message):
        __slots__ = ("cluster_arn", "kafka_topic", "partition_id", "offset", "api_violation_reason", "schema_violation_reason", "message_transformation_failure_reason")
        CLUSTER_ARN_FIELD_NUMBER: _ClassVar[int]
        KAFKA_TOPIC_FIELD_NUMBER: _ClassVar[int]
        PARTITION_ID_FIELD_NUMBER: _ClassVar[int]
        OFFSET_FIELD_NUMBER: _ClassVar[int]
        API_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        SCHEMA_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        MESSAGE_TRANSFORMATION_FAILURE_REASON_FIELD_NUMBER: _ClassVar[int]
        cluster_arn: str
        kafka_topic: str
        partition_id: int
        offset: int
        api_violation_reason: IngestionFailureEvent.ApiViolationReason
        schema_violation_reason: IngestionFailureEvent.SchemaViolationReason
        message_transformation_failure_reason: IngestionFailureEvent.MessageTransformationFailureReason
        def __init__(self, cluster_arn: _Optional[str] = ..., kafka_topic: _Optional[str] = ..., partition_id: _Optional[int] = ..., offset: _Optional[int] = ..., api_violation_reason: _Optional[_Union[IngestionFailureEvent.ApiViolationReason, _Mapping]] = ..., schema_violation_reason: _Optional[_Union[IngestionFailureEvent.SchemaViolationReason, _Mapping]] = ..., message_transformation_failure_reason: _Optional[_Union[IngestionFailureEvent.MessageTransformationFailureReason, _Mapping]] = ...) -> None: ...
    class AzureEventHubsFailureReason(_message.Message):
        __slots__ = ("namespace", "event_hub", "partition_id", "offset", "api_violation_reason", "schema_violation_reason", "message_transformation_failure_reason")
        NAMESPACE_FIELD_NUMBER: _ClassVar[int]
        EVENT_HUB_FIELD_NUMBER: _ClassVar[int]
        PARTITION_ID_FIELD_NUMBER: _ClassVar[int]
        OFFSET_FIELD_NUMBER: _ClassVar[int]
        API_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        SCHEMA_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        MESSAGE_TRANSFORMATION_FAILURE_REASON_FIELD_NUMBER: _ClassVar[int]
        namespace: str
        event_hub: str
        partition_id: int
        offset: int
        api_violation_reason: IngestionFailureEvent.ApiViolationReason
        schema_violation_reason: IngestionFailureEvent.SchemaViolationReason
        message_transformation_failure_reason: IngestionFailureEvent.MessageTransformationFailureReason
        def __init__(self, namespace: _Optional[str] = ..., event_hub: _Optional[str] = ..., partition_id: _Optional[int] = ..., offset: _Optional[int] = ..., api_violation_reason: _Optional[_Union[IngestionFailureEvent.ApiViolationReason, _Mapping]] = ..., schema_violation_reason: _Optional[_Union[IngestionFailureEvent.SchemaViolationReason, _Mapping]] = ..., message_transformation_failure_reason: _Optional[_Union[IngestionFailureEvent.MessageTransformationFailureReason, _Mapping]] = ...) -> None: ...
    class ConfluentCloudFailureReason(_message.Message):
        __slots__ = ("cluster_id", "kafka_topic", "partition_id", "offset", "api_violation_reason", "schema_violation_reason", "message_transformation_failure_reason")
        CLUSTER_ID_FIELD_NUMBER: _ClassVar[int]
        KAFKA_TOPIC_FIELD_NUMBER: _ClassVar[int]
        PARTITION_ID_FIELD_NUMBER: _ClassVar[int]
        OFFSET_FIELD_NUMBER: _ClassVar[int]
        API_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        SCHEMA_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        MESSAGE_TRANSFORMATION_FAILURE_REASON_FIELD_NUMBER: _ClassVar[int]
        cluster_id: str
        kafka_topic: str
        partition_id: int
        offset: int
        api_violation_reason: IngestionFailureEvent.ApiViolationReason
        schema_violation_reason: IngestionFailureEvent.SchemaViolationReason
        message_transformation_failure_reason: IngestionFailureEvent.MessageTransformationFailureReason
        def __init__(self, cluster_id: _Optional[str] = ..., kafka_topic: _Optional[str] = ..., partition_id: _Optional[int] = ..., offset: _Optional[int] = ..., api_violation_reason: _Optional[_Union[IngestionFailureEvent.ApiViolationReason, _Mapping]] = ..., schema_violation_reason: _Optional[_Union[IngestionFailureEvent.SchemaViolationReason, _Mapping]] = ..., message_transformation_failure_reason: _Optional[_Union[IngestionFailureEvent.MessageTransformationFailureReason, _Mapping]] = ...) -> None: ...
    class AwsKinesisFailureReason(_message.Message):
        __slots__ = ("stream_arn", "partition_key", "sequence_number", "schema_violation_reason", "message_transformation_failure_reason", "api_violation_reason")
        STREAM_ARN_FIELD_NUMBER: _ClassVar[int]
        PARTITION_KEY_FIELD_NUMBER: _ClassVar[int]
        SEQUENCE_NUMBER_FIELD_NUMBER: _ClassVar[int]
        SCHEMA_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        MESSAGE_TRANSFORMATION_FAILURE_REASON_FIELD_NUMBER: _ClassVar[int]
        API_VIOLATION_REASON_FIELD_NUMBER: _ClassVar[int]
        stream_arn: str
        partition_key: str
        sequence_number: str
        schema_violation_reason: IngestionFailureEvent.SchemaViolationReason
        message_transformation_failure_reason: IngestionFailureEvent.MessageTransformationFailureReason
        api_violation_reason: IngestionFailureEvent.ApiViolationReason
        def __init__(self, stream_arn: _Optional[str] = ..., partition_key: _Optional[str] = ..., sequence_number: _Optional[str] = ..., schema_violation_reason: _Optional[_Union[IngestionFailureEvent.SchemaViolationReason, _Mapping]] = ..., message_transformation_failure_reason: _Optional[_Union[IngestionFailureEvent.MessageTransformationFailureReason, _Mapping]] = ..., api_violation_reason: _Optional[_Union[IngestionFailureEvent.ApiViolationReason, _Mapping]] = ...) -> None: ...
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CLOUD_STORAGE_FAILURE_FIELD_NUMBER: _ClassVar[int]
    AWS_MSK_FAILURE_FIELD_NUMBER: _ClassVar[int]
    AZURE_EVENT_HUBS_FAILURE_FIELD_NUMBER: _ClassVar[int]
    CONFLUENT_CLOUD_FAILURE_FIELD_NUMBER: _ClassVar[int]
    AWS_KINESIS_FAILURE_FIELD_NUMBER: _ClassVar[int]
    topic: str
    error_message: str
    cloud_storage_failure: IngestionFailureEvent.CloudStorageFailure
    aws_msk_failure: IngestionFailureEvent.AwsMskFailureReason
    azure_event_hubs_failure: IngestionFailureEvent.AzureEventHubsFailureReason
    confluent_cloud_failure: IngestionFailureEvent.ConfluentCloudFailureReason
    aws_kinesis_failure: IngestionFailureEvent.AwsKinesisFailureReason
    def __init__(self, topic: _Optional[str] = ..., error_message: _Optional[str] = ..., cloud_storage_failure: _Optional[_Union[IngestionFailureEvent.CloudStorageFailure, _Mapping]] = ..., aws_msk_failure: _Optional[_Union[IngestionFailureEvent.AwsMskFailureReason, _Mapping]] = ..., azure_event_hubs_failure: _Optional[_Union[IngestionFailureEvent.AzureEventHubsFailureReason, _Mapping]] = ..., confluent_cloud_failure: _Optional[_Union[IngestionFailureEvent.ConfluentCloudFailureReason, _Mapping]] = ..., aws_kinesis_failure: _Optional[_Union[IngestionFailureEvent.AwsKinesisFailureReason, _Mapping]] = ...) -> None: ...

class JavaScriptUDF(_message.Message):
    __slots__ = ("function_name", "code")
    FUNCTION_NAME_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    function_name: str
    code: str
    def __init__(self, function_name: _Optional[str] = ..., code: _Optional[str] = ...) -> None: ...

class AIInference(_message.Message):
    __slots__ = ("endpoint", "unstructured_inference", "service_account_email")
    class UnstructuredInference(_message.Message):
        __slots__ = ("parameters",)
        PARAMETERS_FIELD_NUMBER: _ClassVar[int]
        parameters: _struct_pb2.Struct
        def __init__(self, parameters: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    UNSTRUCTURED_INFERENCE_FIELD_NUMBER: _ClassVar[int]
    SERVICE_ACCOUNT_EMAIL_FIELD_NUMBER: _ClassVar[int]
    endpoint: str
    unstructured_inference: AIInference.UnstructuredInference
    service_account_email: str
    def __init__(self, endpoint: _Optional[str] = ..., unstructured_inference: _Optional[_Union[AIInference.UnstructuredInference, _Mapping]] = ..., service_account_email: _Optional[str] = ...) -> None: ...

class MessageTransform(_message.Message):
    __slots__ = ("javascript_udf", "ai_inference", "enabled", "disabled")
    JAVASCRIPT_UDF_FIELD_NUMBER: _ClassVar[int]
    AI_INFERENCE_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    DISABLED_FIELD_NUMBER: _ClassVar[int]
    javascript_udf: JavaScriptUDF
    ai_inference: AIInference
    enabled: bool
    disabled: bool
    def __init__(self, javascript_udf: _Optional[_Union[JavaScriptUDF, _Mapping]] = ..., ai_inference: _Optional[_Union[AIInference, _Mapping]] = ..., enabled: bool = ..., disabled: bool = ...) -> None: ...

class Topic(_message.Message):
    __slots__ = ("name", "labels", "message_storage_policy", "kms_key_name", "schema_settings", "satisfies_pzs", "message_retention_duration", "state", "ingestion_data_source_settings", "message_transforms", "tags")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[Topic.State]
        ACTIVE: _ClassVar[Topic.State]
        INGESTION_RESOURCE_ERROR: _ClassVar[Topic.State]
    STATE_UNSPECIFIED: Topic.State
    ACTIVE: Topic.State
    INGESTION_RESOURCE_ERROR: Topic.State
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class TagsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_STORAGE_POLICY_FIELD_NUMBER: _ClassVar[int]
    KMS_KEY_NAME_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    SATISFIES_PZS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_RETENTION_DURATION_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    INGESTION_DATA_SOURCE_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TRANSFORMS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    labels: _containers.ScalarMap[str, str]
    message_storage_policy: MessageStoragePolicy
    kms_key_name: str
    schema_settings: SchemaSettings
    satisfies_pzs: bool
    message_retention_duration: _duration_pb2.Duration
    state: Topic.State
    ingestion_data_source_settings: IngestionDataSourceSettings
    message_transforms: _containers.RepeatedCompositeFieldContainer[MessageTransform]
    tags: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., labels: _Optional[_Mapping[str, str]] = ..., message_storage_policy: _Optional[_Union[MessageStoragePolicy, _Mapping]] = ..., kms_key_name: _Optional[str] = ..., schema_settings: _Optional[_Union[SchemaSettings, _Mapping]] = ..., satisfies_pzs: bool = ..., message_retention_duration: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., state: _Optional[_Union[Topic.State, str]] = ..., ingestion_data_source_settings: _Optional[_Union[IngestionDataSourceSettings, _Mapping]] = ..., message_transforms: _Optional[_Iterable[_Union[MessageTransform, _Mapping]]] = ..., tags: _Optional[_Mapping[str, str]] = ...) -> None: ...

class PubsubMessage(_message.Message):
    __slots__ = ("data", "attributes", "message_id", "publish_time", "ordering_key")
    class AttributesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DATA_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PUBLISH_TIME_FIELD_NUMBER: _ClassVar[int]
    ORDERING_KEY_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    attributes: _containers.ScalarMap[str, str]
    message_id: str
    publish_time: _timestamp_pb2.Timestamp
    ordering_key: str
    def __init__(self, data: _Optional[bytes] = ..., attributes: _Optional[_Mapping[str, str]] = ..., message_id: _Optional[str] = ..., publish_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., ordering_key: _Optional[str] = ...) -> None: ...

class GetTopicRequest(_message.Message):
    __slots__ = ("topic",)
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    topic: str
    def __init__(self, topic: _Optional[str] = ...) -> None: ...

class UpdateTopicRequest(_message.Message):
    __slots__ = ("topic", "update_mask")
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    topic: Topic
    update_mask: _field_mask_pb2.FieldMask
    def __init__(self, topic: _Optional[_Union[Topic, _Mapping]] = ..., update_mask: _Optional[_Union[_field_mask_pb2.FieldMask, _Mapping]] = ...) -> None: ...

class PublishRequest(_message.Message):
    __slots__ = ("topic", "messages")
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    topic: str
    messages: _containers.RepeatedCompositeFieldContainer[PubsubMessage]
    def __init__(self, topic: _Optional[str] = ..., messages: _Optional[_Iterable[_Union[PubsubMessage, _Mapping]]] = ...) -> None: ...

class PublishResponse(_message.Message):
    __slots__ = ("message_ids",)
    MESSAGE_IDS_FIELD_NUMBER: _ClassVar[int]
    message_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, message_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class ListTopicsRequest(_message.Message):
    __slots__ = ("project", "page_size", "page_token")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    project: str
    page_size: int
    page_token: str
    def __init__(self, project: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListTopicsResponse(_message.Message):
    __slots__ = ("topics", "next_page_token")
    TOPICS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    topics: _containers.RepeatedCompositeFieldContainer[Topic]
    next_page_token: str
    def __init__(self, topics: _Optional[_Iterable[_Union[Topic, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class ListTopicSubscriptionsRequest(_message.Message):
    __slots__ = ("topic", "page_size", "page_token")
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    topic: str
    page_size: int
    page_token: str
    def __init__(self, topic: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListTopicSubscriptionsResponse(_message.Message):
    __slots__ = ("subscriptions", "next_page_token")
    SUBSCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    subscriptions: _containers.RepeatedScalarFieldContainer[str]
    next_page_token: str
    def __init__(self, subscriptions: _Optional[_Iterable[str]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class ListTopicSnapshotsRequest(_message.Message):
    __slots__ = ("topic", "page_size", "page_token")
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    topic: str
    page_size: int
    page_token: str
    def __init__(self, topic: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListTopicSnapshotsResponse(_message.Message):
    __slots__ = ("snapshots", "next_page_token")
    SNAPSHOTS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    snapshots: _containers.RepeatedScalarFieldContainer[str]
    next_page_token: str
    def __init__(self, snapshots: _Optional[_Iterable[str]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class DeleteTopicRequest(_message.Message):
    __slots__ = ("topic",)
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    topic: str
    def __init__(self, topic: _Optional[str] = ...) -> None: ...

class DetachSubscriptionRequest(_message.Message):
    __slots__ = ("subscription",)
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    def __init__(self, subscription: _Optional[str] = ...) -> None: ...

class DetachSubscriptionResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Subscription(_message.Message):
    __slots__ = ("name", "topic", "push_config", "bigquery_config", "cloud_storage_config", "bigtable_config", "ack_deadline_seconds", "retain_acked_messages", "message_retention_duration", "labels", "enable_message_ordering", "expiration_policy", "filter", "dead_letter_policy", "retry_policy", "detached", "enable_exactly_once_delivery", "topic_message_retention_duration", "state", "analytics_hub_subscription_info", "message_transforms", "tags")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[Subscription.State]
        ACTIVE: _ClassVar[Subscription.State]
        RESOURCE_ERROR: _ClassVar[Subscription.State]
    STATE_UNSPECIFIED: Subscription.State
    ACTIVE: Subscription.State
    RESOURCE_ERROR: Subscription.State
    class AnalyticsHubSubscriptionInfo(_message.Message):
        __slots__ = ("listing", "subscription")
        LISTING_FIELD_NUMBER: _ClassVar[int]
        SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
        listing: str
        subscription: str
        def __init__(self, listing: _Optional[str] = ..., subscription: _Optional[str] = ...) -> None: ...
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class TagsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    PUSH_CONFIG_FIELD_NUMBER: _ClassVar[int]
    BIGQUERY_CONFIG_FIELD_NUMBER: _ClassVar[int]
    CLOUD_STORAGE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    BIGTABLE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    ACK_DEADLINE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    RETAIN_ACKED_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_RETENTION_DURATION_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    ENABLE_MESSAGE_ORDERING_FIELD_NUMBER: _ClassVar[int]
    EXPIRATION_POLICY_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    DEAD_LETTER_POLICY_FIELD_NUMBER: _ClassVar[int]
    RETRY_POLICY_FIELD_NUMBER: _ClassVar[int]
    DETACHED_FIELD_NUMBER: _ClassVar[int]
    ENABLE_EXACTLY_ONCE_DELIVERY_FIELD_NUMBER: _ClassVar[int]
    TOPIC_MESSAGE_RETENTION_DURATION_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ANALYTICS_HUB_SUBSCRIPTION_INFO_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TRANSFORMS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    topic: str
    push_config: PushConfig
    bigquery_config: BigQueryConfig
    cloud_storage_config: CloudStorageConfig
    bigtable_config: BigtableConfig
    ack_deadline_seconds: int
    retain_acked_messages: bool
    message_retention_duration: _duration_pb2.Duration
    labels: _containers.ScalarMap[str, str]
    enable_message_ordering: bool
    expiration_policy: ExpirationPolicy
    filter: str
    dead_letter_policy: DeadLetterPolicy
    retry_policy: RetryPolicy
    detached: bool
    enable_exactly_once_delivery: bool
    topic_message_retention_duration: _duration_pb2.Duration
    state: Subscription.State
    analytics_hub_subscription_info: Subscription.AnalyticsHubSubscriptionInfo
    message_transforms: _containers.RepeatedCompositeFieldContainer[MessageTransform]
    tags: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., topic: _Optional[str] = ..., push_config: _Optional[_Union[PushConfig, _Mapping]] = ..., bigquery_config: _Optional[_Union[BigQueryConfig, _Mapping]] = ..., cloud_storage_config: _Optional[_Union[CloudStorageConfig, _Mapping]] = ..., bigtable_config: _Optional[_Union[BigtableConfig, _Mapping]] = ..., ack_deadline_seconds: _Optional[int] = ..., retain_acked_messages: bool = ..., message_retention_duration: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., labels: _Optional[_Mapping[str, str]] = ..., enable_message_ordering: bool = ..., expiration_policy: _Optional[_Union[ExpirationPolicy, _Mapping]] = ..., filter: _Optional[str] = ..., dead_letter_policy: _Optional[_Union[DeadLetterPolicy, _Mapping]] = ..., retry_policy: _Optional[_Union[RetryPolicy, _Mapping]] = ..., detached: bool = ..., enable_exactly_once_delivery: bool = ..., topic_message_retention_duration: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., state: _Optional[_Union[Subscription.State, str]] = ..., analytics_hub_subscription_info: _Optional[_Union[Subscription.AnalyticsHubSubscriptionInfo, _Mapping]] = ..., message_transforms: _Optional[_Iterable[_Union[MessageTransform, _Mapping]]] = ..., tags: _Optional[_Mapping[str, str]] = ...) -> None: ...

class RetryPolicy(_message.Message):
    __slots__ = ("minimum_backoff", "maximum_backoff")
    MINIMUM_BACKOFF_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_BACKOFF_FIELD_NUMBER: _ClassVar[int]
    minimum_backoff: _duration_pb2.Duration
    maximum_backoff: _duration_pb2.Duration
    def __init__(self, minimum_backoff: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., maximum_backoff: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class DeadLetterPolicy(_message.Message):
    __slots__ = ("dead_letter_topic", "max_delivery_attempts")
    DEAD_LETTER_TOPIC_FIELD_NUMBER: _ClassVar[int]
    MAX_DELIVERY_ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    dead_letter_topic: str
    max_delivery_attempts: int
    def __init__(self, dead_letter_topic: _Optional[str] = ..., max_delivery_attempts: _Optional[int] = ...) -> None: ...

class ExpirationPolicy(_message.Message):
    __slots__ = ("ttl",)
    TTL_FIELD_NUMBER: _ClassVar[int]
    ttl: _duration_pb2.Duration
    def __init__(self, ttl: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class PushConfig(_message.Message):
    __slots__ = ("push_endpoint", "attributes", "oidc_token", "pubsub_wrapper", "no_wrapper")
    class OidcToken(_message.Message):
        __slots__ = ("service_account_email", "audience")
        SERVICE_ACCOUNT_EMAIL_FIELD_NUMBER: _ClassVar[int]
        AUDIENCE_FIELD_NUMBER: _ClassVar[int]
        service_account_email: str
        audience: str
        def __init__(self, service_account_email: _Optional[str] = ..., audience: _Optional[str] = ...) -> None: ...
    class PubsubWrapper(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class NoWrapper(_message.Message):
        __slots__ = ("write_metadata",)
        WRITE_METADATA_FIELD_NUMBER: _ClassVar[int]
        write_metadata: bool
        def __init__(self, write_metadata: bool = ...) -> None: ...
    class AttributesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PUSH_ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    OIDC_TOKEN_FIELD_NUMBER: _ClassVar[int]
    PUBSUB_WRAPPER_FIELD_NUMBER: _ClassVar[int]
    NO_WRAPPER_FIELD_NUMBER: _ClassVar[int]
    push_endpoint: str
    attributes: _containers.ScalarMap[str, str]
    oidc_token: PushConfig.OidcToken
    pubsub_wrapper: PushConfig.PubsubWrapper
    no_wrapper: PushConfig.NoWrapper
    def __init__(self, push_endpoint: _Optional[str] = ..., attributes: _Optional[_Mapping[str, str]] = ..., oidc_token: _Optional[_Union[PushConfig.OidcToken, _Mapping]] = ..., pubsub_wrapper: _Optional[_Union[PushConfig.PubsubWrapper, _Mapping]] = ..., no_wrapper: _Optional[_Union[PushConfig.NoWrapper, _Mapping]] = ...) -> None: ...

class BigQueryConfig(_message.Message):
    __slots__ = ("table", "use_topic_schema", "write_metadata", "drop_unknown_fields", "state", "use_table_schema", "service_account_email")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[BigQueryConfig.State]
        ACTIVE: _ClassVar[BigQueryConfig.State]
        PERMISSION_DENIED: _ClassVar[BigQueryConfig.State]
        NOT_FOUND: _ClassVar[BigQueryConfig.State]
        SCHEMA_MISMATCH: _ClassVar[BigQueryConfig.State]
        IN_TRANSIT_LOCATION_RESTRICTION: _ClassVar[BigQueryConfig.State]
        VERTEX_AI_LOCATION_RESTRICTION: _ClassVar[BigQueryConfig.State]
    STATE_UNSPECIFIED: BigQueryConfig.State
    ACTIVE: BigQueryConfig.State
    PERMISSION_DENIED: BigQueryConfig.State
    NOT_FOUND: BigQueryConfig.State
    SCHEMA_MISMATCH: BigQueryConfig.State
    IN_TRANSIT_LOCATION_RESTRICTION: BigQueryConfig.State
    VERTEX_AI_LOCATION_RESTRICTION: BigQueryConfig.State
    TABLE_FIELD_NUMBER: _ClassVar[int]
    USE_TOPIC_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    WRITE_METADATA_FIELD_NUMBER: _ClassVar[int]
    DROP_UNKNOWN_FIELDS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    USE_TABLE_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    SERVICE_ACCOUNT_EMAIL_FIELD_NUMBER: _ClassVar[int]
    table: str
    use_topic_schema: bool
    write_metadata: bool
    drop_unknown_fields: bool
    state: BigQueryConfig.State
    use_table_schema: bool
    service_account_email: str
    def __init__(self, table: _Optional[str] = ..., use_topic_schema: bool = ..., write_metadata: bool = ..., drop_unknown_fields: bool = ..., state: _Optional[_Union[BigQueryConfig.State, str]] = ..., use_table_schema: bool = ..., service_account_email: _Optional[str] = ...) -> None: ...

class BigtableConfig(_message.Message):
    __slots__ = ("table", "app_profile_id", "service_account_email", "write_metadata", "state")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[BigtableConfig.State]
        ACTIVE: _ClassVar[BigtableConfig.State]
        NOT_FOUND: _ClassVar[BigtableConfig.State]
        APP_PROFILE_MISCONFIGURED: _ClassVar[BigtableConfig.State]
        PERMISSION_DENIED: _ClassVar[BigtableConfig.State]
        SCHEMA_MISMATCH: _ClassVar[BigtableConfig.State]
        IN_TRANSIT_LOCATION_RESTRICTION: _ClassVar[BigtableConfig.State]
        VERTEX_AI_LOCATION_RESTRICTION: _ClassVar[BigtableConfig.State]
    STATE_UNSPECIFIED: BigtableConfig.State
    ACTIVE: BigtableConfig.State
    NOT_FOUND: BigtableConfig.State
    APP_PROFILE_MISCONFIGURED: BigtableConfig.State
    PERMISSION_DENIED: BigtableConfig.State
    SCHEMA_MISMATCH: BigtableConfig.State
    IN_TRANSIT_LOCATION_RESTRICTION: BigtableConfig.State
    VERTEX_AI_LOCATION_RESTRICTION: BigtableConfig.State
    TABLE_FIELD_NUMBER: _ClassVar[int]
    APP_PROFILE_ID_FIELD_NUMBER: _ClassVar[int]
    SERVICE_ACCOUNT_EMAIL_FIELD_NUMBER: _ClassVar[int]
    WRITE_METADATA_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    table: str
    app_profile_id: str
    service_account_email: str
    write_metadata: bool
    state: BigtableConfig.State
    def __init__(self, table: _Optional[str] = ..., app_profile_id: _Optional[str] = ..., service_account_email: _Optional[str] = ..., write_metadata: bool = ..., state: _Optional[_Union[BigtableConfig.State, str]] = ...) -> None: ...

class CloudStorageConfig(_message.Message):
    __slots__ = ("bucket", "filename_prefix", "filename_suffix", "filename_datetime_format", "text_config", "avro_config", "max_duration", "max_bytes", "max_messages", "state", "service_account_email")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[CloudStorageConfig.State]
        ACTIVE: _ClassVar[CloudStorageConfig.State]
        PERMISSION_DENIED: _ClassVar[CloudStorageConfig.State]
        NOT_FOUND: _ClassVar[CloudStorageConfig.State]
        IN_TRANSIT_LOCATION_RESTRICTION: _ClassVar[CloudStorageConfig.State]
        SCHEMA_MISMATCH: _ClassVar[CloudStorageConfig.State]
        VERTEX_AI_LOCATION_RESTRICTION: _ClassVar[CloudStorageConfig.State]
    STATE_UNSPECIFIED: CloudStorageConfig.State
    ACTIVE: CloudStorageConfig.State
    PERMISSION_DENIED: CloudStorageConfig.State
    NOT_FOUND: CloudStorageConfig.State
    IN_TRANSIT_LOCATION_RESTRICTION: CloudStorageConfig.State
    SCHEMA_MISMATCH: CloudStorageConfig.State
    VERTEX_AI_LOCATION_RESTRICTION: CloudStorageConfig.State
    class TextConfig(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class AvroConfig(_message.Message):
        __slots__ = ("write_metadata", "use_topic_schema")
        WRITE_METADATA_FIELD_NUMBER: _ClassVar[int]
        USE_TOPIC_SCHEMA_FIELD_NUMBER: _ClassVar[int]
        write_metadata: bool
        use_topic_schema: bool
        def __init__(self, write_metadata: bool = ..., use_topic_schema: bool = ...) -> None: ...
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    FILENAME_PREFIX_FIELD_NUMBER: _ClassVar[int]
    FILENAME_SUFFIX_FIELD_NUMBER: _ClassVar[int]
    FILENAME_DATETIME_FORMAT_FIELD_NUMBER: _ClassVar[int]
    TEXT_CONFIG_FIELD_NUMBER: _ClassVar[int]
    AVRO_CONFIG_FIELD_NUMBER: _ClassVar[int]
    MAX_DURATION_FIELD_NUMBER: _ClassVar[int]
    MAX_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    SERVICE_ACCOUNT_EMAIL_FIELD_NUMBER: _ClassVar[int]
    bucket: str
    filename_prefix: str
    filename_suffix: str
    filename_datetime_format: str
    text_config: CloudStorageConfig.TextConfig
    avro_config: CloudStorageConfig.AvroConfig
    max_duration: _duration_pb2.Duration
    max_bytes: int
    max_messages: int
    state: CloudStorageConfig.State
    service_account_email: str
    def __init__(self, bucket: _Optional[str] = ..., filename_prefix: _Optional[str] = ..., filename_suffix: _Optional[str] = ..., filename_datetime_format: _Optional[str] = ..., text_config: _Optional[_Union[CloudStorageConfig.TextConfig, _Mapping]] = ..., avro_config: _Optional[_Union[CloudStorageConfig.AvroConfig, _Mapping]] = ..., max_duration: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., max_bytes: _Optional[int] = ..., max_messages: _Optional[int] = ..., state: _Optional[_Union[CloudStorageConfig.State, str]] = ..., service_account_email: _Optional[str] = ...) -> None: ...

class ReceivedMessage(_message.Message):
    __slots__ = ("ack_id", "message", "delivery_attempt")
    ACK_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DELIVERY_ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    ack_id: str
    message: PubsubMessage
    delivery_attempt: int
    def __init__(self, ack_id: _Optional[str] = ..., message: _Optional[_Union[PubsubMessage, _Mapping]] = ..., delivery_attempt: _Optional[int] = ...) -> None: ...

class GetSubscriptionRequest(_message.Message):
    __slots__ = ("subscription",)
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    def __init__(self, subscription: _Optional[str] = ...) -> None: ...

class UpdateSubscriptionRequest(_message.Message):
    __slots__ = ("subscription", "update_mask")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    subscription: Subscription
    update_mask: _field_mask_pb2.FieldMask
    def __init__(self, subscription: _Optional[_Union[Subscription, _Mapping]] = ..., update_mask: _Optional[_Union[_field_mask_pb2.FieldMask, _Mapping]] = ...) -> None: ...

class ListSubscriptionsRequest(_message.Message):
    __slots__ = ("project", "page_size", "page_token")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    project: str
    page_size: int
    page_token: str
    def __init__(self, project: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListSubscriptionsResponse(_message.Message):
    __slots__ = ("subscriptions", "next_page_token")
    SUBSCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    subscriptions: _containers.RepeatedCompositeFieldContainer[Subscription]
    next_page_token: str
    def __init__(self, subscriptions: _Optional[_Iterable[_Union[Subscription, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class DeleteSubscriptionRequest(_message.Message):
    __slots__ = ("subscription",)
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    def __init__(self, subscription: _Optional[str] = ...) -> None: ...

class ModifyPushConfigRequest(_message.Message):
    __slots__ = ("subscription", "push_config")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PUSH_CONFIG_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    push_config: PushConfig
    def __init__(self, subscription: _Optional[str] = ..., push_config: _Optional[_Union[PushConfig, _Mapping]] = ...) -> None: ...

class PullRequest(_message.Message):
    __slots__ = ("subscription", "return_immediately", "max_messages")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    RETURN_IMMEDIATELY_FIELD_NUMBER: _ClassVar[int]
    MAX_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    return_immediately: bool
    max_messages: int
    def __init__(self, subscription: _Optional[str] = ..., return_immediately: bool = ..., max_messages: _Optional[int] = ...) -> None: ...

class PullResponse(_message.Message):
    __slots__ = ("received_messages",)
    RECEIVED_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    received_messages: _containers.RepeatedCompositeFieldContainer[ReceivedMessage]
    def __init__(self, received_messages: _Optional[_Iterable[_Union[ReceivedMessage, _Mapping]]] = ...) -> None: ...

class ModifyAckDeadlineRequest(_message.Message):
    __slots__ = ("subscription", "ack_ids", "ack_deadline_seconds")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ACK_IDS_FIELD_NUMBER: _ClassVar[int]
    ACK_DEADLINE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    ack_ids: _containers.RepeatedScalarFieldContainer[str]
    ack_deadline_seconds: int
    def __init__(self, subscription: _Optional[str] = ..., ack_ids: _Optional[_Iterable[str]] = ..., ack_deadline_seconds: _Optional[int] = ...) -> None: ...

class AcknowledgeRequest(_message.Message):
    __slots__ = ("subscription", "ack_ids")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ACK_IDS_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    ack_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, subscription: _Optional[str] = ..., ack_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class StreamingPullRequest(_message.Message):
    __slots__ = ("subscription", "ack_ids", "modify_deadline_seconds", "modify_deadline_ack_ids", "stream_ack_deadline_seconds", "client_id", "max_outstanding_messages", "max_outstanding_bytes", "protocol_version")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ACK_IDS_FIELD_NUMBER: _ClassVar[int]
    MODIFY_DEADLINE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    MODIFY_DEADLINE_ACK_IDS_FIELD_NUMBER: _ClassVar[int]
    STREAM_ACK_DEADLINE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTSTANDING_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTSTANDING_BYTES_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    ack_ids: _containers.RepeatedScalarFieldContainer[str]
    modify_deadline_seconds: _containers.RepeatedScalarFieldContainer[int]
    modify_deadline_ack_ids: _containers.RepeatedScalarFieldContainer[str]
    stream_ack_deadline_seconds: int
    client_id: str
    max_outstanding_messages: int
    max_outstanding_bytes: int
    protocol_version: int
    def __init__(self, subscription: _Optional[str] = ..., ack_ids: _Optional[_Iterable[str]] = ..., modify_deadline_seconds: _Optional[_Iterable[int]] = ..., modify_deadline_ack_ids: _Optional[_Iterable[str]] = ..., stream_ack_deadline_seconds: _Optional[int] = ..., client_id: _Optional[str] = ..., max_outstanding_messages: _Optional[int] = ..., max_outstanding_bytes: _Optional[int] = ..., protocol_version: _Optional[int] = ...) -> None: ...

class StreamingPullResponse(_message.Message):
    __slots__ = ("received_messages", "acknowledge_confirmation", "modify_ack_deadline_confirmation", "subscription_properties")
    class AcknowledgeConfirmation(_message.Message):
        __slots__ = ("ack_ids", "invalid_ack_ids", "unordered_ack_ids", "temporary_failed_ack_ids")
        ACK_IDS_FIELD_NUMBER: _ClassVar[int]
        INVALID_ACK_IDS_FIELD_NUMBER: _ClassVar[int]
        UNORDERED_ACK_IDS_FIELD_NUMBER: _ClassVar[int]
        TEMPORARY_FAILED_ACK_IDS_FIELD_NUMBER: _ClassVar[int]
        ack_ids: _containers.RepeatedScalarFieldContainer[str]
        invalid_ack_ids: _containers.RepeatedScalarFieldContainer[str]
        unordered_ack_ids: _containers.RepeatedScalarFieldContainer[str]
        temporary_failed_ack_ids: _containers.RepeatedScalarFieldContainer[str]
        def __init__(self, ack_ids: _Optional[_Iterable[str]] = ..., invalid_ack_ids: _Optional[_Iterable[str]] = ..., unordered_ack_ids: _Optional[_Iterable[str]] = ..., temporary_failed_ack_ids: _Optional[_Iterable[str]] = ...) -> None: ...
    class ModifyAckDeadlineConfirmation(_message.Message):
        __slots__ = ("ack_ids", "invalid_ack_ids", "temporary_failed_ack_ids")
        ACK_IDS_FIELD_NUMBER: _ClassVar[int]
        INVALID_ACK_IDS_FIELD_NUMBER: _ClassVar[int]
        TEMPORARY_FAILED_ACK_IDS_FIELD_NUMBER: _ClassVar[int]
        ack_ids: _containers.RepeatedScalarFieldContainer[str]
        invalid_ack_ids: _containers.RepeatedScalarFieldContainer[str]
        temporary_failed_ack_ids: _containers.RepeatedScalarFieldContainer[str]
        def __init__(self, ack_ids: _Optional[_Iterable[str]] = ..., invalid_ack_ids: _Optional[_Iterable[str]] = ..., temporary_failed_ack_ids: _Optional[_Iterable[str]] = ...) -> None: ...
    class SubscriptionProperties(_message.Message):
        __slots__ = ("exactly_once_delivery_enabled", "message_ordering_enabled")
        EXACTLY_ONCE_DELIVERY_ENABLED_FIELD_NUMBER: _ClassVar[int]
        MESSAGE_ORDERING_ENABLED_FIELD_NUMBER: _ClassVar[int]
        exactly_once_delivery_enabled: bool
        message_ordering_enabled: bool
        def __init__(self, exactly_once_delivery_enabled: bool = ..., message_ordering_enabled: bool = ...) -> None: ...
    RECEIVED_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    ACKNOWLEDGE_CONFIRMATION_FIELD_NUMBER: _ClassVar[int]
    MODIFY_ACK_DEADLINE_CONFIRMATION_FIELD_NUMBER: _ClassVar[int]
    SUBSCRIPTION_PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    received_messages: _containers.RepeatedCompositeFieldContainer[ReceivedMessage]
    acknowledge_confirmation: StreamingPullResponse.AcknowledgeConfirmation
    modify_ack_deadline_confirmation: StreamingPullResponse.ModifyAckDeadlineConfirmation
    subscription_properties: StreamingPullResponse.SubscriptionProperties
    def __init__(self, received_messages: _Optional[_Iterable[_Union[ReceivedMessage, _Mapping]]] = ..., acknowledge_confirmation: _Optional[_Union[StreamingPullResponse.AcknowledgeConfirmation, _Mapping]] = ..., modify_ack_deadline_confirmation: _Optional[_Union[StreamingPullResponse.ModifyAckDeadlineConfirmation, _Mapping]] = ..., subscription_properties: _Optional[_Union[StreamingPullResponse.SubscriptionProperties, _Mapping]] = ...) -> None: ...

class CreateSnapshotRequest(_message.Message):
    __slots__ = ("name", "subscription", "labels", "tags")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class TagsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    name: str
    subscription: str
    labels: _containers.ScalarMap[str, str]
    tags: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., subscription: _Optional[str] = ..., labels: _Optional[_Mapping[str, str]] = ..., tags: _Optional[_Mapping[str, str]] = ...) -> None: ...

class UpdateSnapshotRequest(_message.Message):
    __slots__ = ("snapshot", "update_mask")
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    UPDATE_MASK_FIELD_NUMBER: _ClassVar[int]
    snapshot: Snapshot
    update_mask: _field_mask_pb2.FieldMask
    def __init__(self, snapshot: _Optional[_Union[Snapshot, _Mapping]] = ..., update_mask: _Optional[_Union[_field_mask_pb2.FieldMask, _Mapping]] = ...) -> None: ...

class Snapshot(_message.Message):
    __slots__ = ("name", "topic", "expire_time", "labels")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    EXPIRE_TIME_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    name: str
    topic: str
    expire_time: _timestamp_pb2.Timestamp
    labels: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., topic: _Optional[str] = ..., expire_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., labels: _Optional[_Mapping[str, str]] = ...) -> None: ...

class GetSnapshotRequest(_message.Message):
    __slots__ = ("snapshot",)
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    snapshot: str
    def __init__(self, snapshot: _Optional[str] = ...) -> None: ...

class ListSnapshotsRequest(_message.Message):
    __slots__ = ("project", "page_size", "page_token")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    project: str
    page_size: int
    page_token: str
    def __init__(self, project: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListSnapshotsResponse(_message.Message):
    __slots__ = ("snapshots", "next_page_token")
    SNAPSHOTS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    snapshots: _containers.RepeatedCompositeFieldContainer[Snapshot]
    next_page_token: str
    def __init__(self, snapshots: _Optional[_Iterable[_Union[Snapshot, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class DeleteSnapshotRequest(_message.Message):
    __slots__ = ("snapshot",)
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    snapshot: str
    def __init__(self, snapshot: _Optional[str] = ...) -> None: ...

class SeekRequest(_message.Message):
    __slots__ = ("subscription", "time", "snapshot")
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    TIME_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    subscription: str
    time: _timestamp_pb2.Timestamp
    snapshot: str
    def __init__(self, subscription: _Optional[str] = ..., time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., snapshot: _Optional[str] = ...) -> None: ...

class SeekResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
