"""Pydantic response models for the ui-api."""

from pydantic import BaseModel


class PortInfo(BaseModel):
    number: int
    protocol: str


class ServiceInfo(BaseModel):
    name: str
    ports: list[PortInfo]
    ui_supported: bool


class ServiceList(BaseModel):
    services: list[ServiceInfo]
    version: str
