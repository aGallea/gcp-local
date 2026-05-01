"""Test helpers for building StructuredQuery protos that work across protobuf versions."""

from gcp_local.generated.google.firestore.v1 import query_pb2


def set_from(sq: query_pb2.StructuredQuery, selectors: list) -> None:
    """Append CollectionSelectors to sq's ``from`` field, robust to renaming.

    Different protobuf runtimes expose the reserved-word ``from`` field as
    either ``from`` or ``from_``, and either form can raise ``AttributeError``
    or ``ValueError`` on the wrong runtime.  We try both names inside a guard.
    """
    for name in ("from_", "from"):
        try:
            field = getattr(sq, name)
        except (AttributeError, ValueError):
            continue
        field.extend(selectors)
        return
    raise AttributeError("StructuredQuery exposes neither 'from' nor 'from_'")
