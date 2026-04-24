from importlib.metadata import entry_points

from gcp_local.core.service import Service


class UnknownServiceError(KeyError):
    pass


class ServiceRegistry:
    """Holds the set of services that have been registered in this process.

    Services can be registered programmatically (tests) or discovered via
    Python entry points in the `gcp_local.services` group.
    """

    def __init__(self) -> None:
        self._classes: dict[str, type[Service]] = {}

    def register(self, name: str, service_cls: type[Service]) -> None:
        if name in self._classes:
            raise ValueError(f"service {name!r} already registered")
        self._classes[name] = service_cls

    def get(self, name: str) -> type[Service]:
        try:
            return self._classes[name]
        except KeyError:
            raise UnknownServiceError(name) from None

    def names(self) -> list[str]:
        return sorted(self._classes)

    def discover_from_entry_points(self, group: str = "gcp_local.services") -> None:
        for ep in entry_points(group=group):
            cls = ep.load()
            self.register(ep.name, cls)

    def resolve_selection(self, spec: str) -> list[str]:
        """Resolve a `SERVICES` env value to a sorted list of service names.

        Accepted values:
          - "all"  -> every registered service
          - ""     -> no services
          - comma-separated names -> those services, sorted
        """
        spec = spec.strip()
        if spec == "all":
            return self.names()
        if not spec:
            return []
        requested = sorted({s.strip() for s in spec.split(",") if s.strip()})
        unknown = [s for s in requested if s not in self._classes]
        if unknown:
            raise UnknownServiceError(", ".join(unknown))
        return requested
