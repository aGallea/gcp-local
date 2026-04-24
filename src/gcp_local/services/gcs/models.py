from pydantic import BaseModel, ConfigDict, Field, computed_field


class BucketMeta(BaseModel):
    model_config = ConfigDict(frozen=False)

    name: str
    time_created: str
    metageneration: int = 1
    location: str = "US"
    storage_class: str = "STANDARD"


class ObjectRecord(BaseModel):
    model_config = ConfigDict(frozen=False, populate_by_name=True)

    bucket: str
    name: str
    size: int
    generation: int
    metageneration: int
    content_type: str = Field(default="application/octet-stream", serialization_alias="contentType")
    content_encoding: str = Field(default="", serialization_alias="contentEncoding")
    content_language: str = Field(default="", serialization_alias="contentLanguage")
    content_disposition: str = Field(default="", serialization_alias="contentDisposition")
    cache_control: str = Field(default="", serialization_alias="cacheControl")
    md5_hash: str = Field(serialization_alias="md5Hash")
    crc32c: str
    time_created: str = Field(serialization_alias="timeCreated")
    updated: str
    metadata: dict[str, str] = Field(default_factory=dict)

    @computed_field
    def etag(self) -> str:
        return f'"{self.generation}/{self.metageneration}"'


class UploadSession(BaseModel):
    model_config = ConfigDict(frozen=False)

    session_id: str
    bucket: str
    object_name: str
    total_size: int | None
    bytes_received: int
    content_type: str
    user_metadata: dict[str, str] = Field(default_factory=dict)
    created_at: str
    last_chunk_at: str

    @property
    def is_complete(self) -> bool:
        return self.total_size is not None and self.bytes_received >= self.total_size
