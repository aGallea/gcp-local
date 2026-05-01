"""Firestore gRPC servicers. RPCs are filled in by later tasks."""

from gcp_local.core.state_hub import StateHub
from gcp_local.generated.google.firestore.admin.v1 import firestore_admin_pb2_grpc
from gcp_local.generated.google.firestore.v1 import firestore_pb2_grpc
from gcp_local.services.firestore.storage import FirestoreStorage


class FirestoreServicer(firestore_pb2_grpc.FirestoreServicer):  # type: ignore[misc, name-defined]
    def __init__(self, storage: FirestoreStorage, state_hub: StateHub | None) -> None:
        self._storage = storage
        self._state_hub = state_hub


class FirestoreAdminServicer(firestore_admin_pb2_grpc.FirestoreAdminServicer):  # type: ignore[misc, name-defined]
    def __init__(self, storage: FirestoreStorage) -> None:
        self._storage = storage
