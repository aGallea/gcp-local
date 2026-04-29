"""Pub/Sub gRPC servicers.

This file holds the bridge from gRPC requests to the storage / backlog
layers. Methods are added incrementally — see the implementation plan
for the order (topic CRUD → publish → subscription CRUD → pull → ack
→ streaming pull → seek).
"""

from gcp_local.generated.google.pubsub.v1 import pubsub_pb2_grpc
from gcp_local.services.pubsub.storage import PubSubStorage


class PublisherServicer(pubsub_pb2_grpc.PublisherServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage


class SubscriberServicer(pubsub_pb2_grpc.SubscriberServicer):
    def __init__(self, *, storage: PubSubStorage) -> None:
        self._storage = storage
