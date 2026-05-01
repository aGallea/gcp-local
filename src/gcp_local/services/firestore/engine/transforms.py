"""Firestore field transforms applied during Commit."""

from datetime import datetime
from typing import Any

from gcp_local.generated.google.firestore.v1 import write_pb2
from gcp_local.services.firestore.errors import InvalidArgument
from gcp_local.services.firestore.values import compare, from_proto

_MISSING = object()


def _set_dotted(fields: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = fields
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _get_dotted(fields: dict[str, Any], path: str) -> Any:
    cur: Any = fields
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return _MISSING
        cur = cur[p]
    return cur


def apply_transform(
    fields: dict[str, Any],
    transform: write_pb2.DocumentTransform.FieldTransform,
    server_time: datetime,
) -> tuple[dict[str, Any], Any]:
    """Apply one field transform to a copy of `fields`. Returns (new_fields, result_value)."""
    new_fields = _deep_copy(fields)
    path = transform.field_path
    which = transform.WhichOneof("transform_type")

    if which == "set_to_server_value":
        if transform.set_to_server_value != write_pb2.DocumentTransform.FieldTransform.REQUEST_TIME:
            raise InvalidArgument("only REQUEST_TIME server values supported")
        _set_dotted(new_fields, path, server_time)
        return new_fields, server_time

    if which == "increment":
        delta = from_proto(transform.increment)
        if not isinstance(delta, (int, float)) or isinstance(delta, bool):
            raise InvalidArgument(f"increment requires numeric value, got {type(delta).__name__}")
        existing = _get_dotted(new_fields, path)
        if (
            existing is _MISSING
            or not isinstance(existing, (int, float))
            or isinstance(existing, bool)
        ):
            existing = 0
        result = existing + delta
        # Type promotion: int+int → int; double anywhere → float
        if isinstance(existing, int) and isinstance(delta, int):
            result = int(result)
        else:
            result = float(result)
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "maximum":
        candidate = from_proto(transform.maximum)
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING:
            result = candidate
        else:
            result = candidate if compare(candidate, existing) > 0 else existing
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "minimum":
        candidate = from_proto(transform.minimum)
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING:
            result = candidate
        else:
            result = candidate if compare(candidate, existing) < 0 else existing
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "append_missing_elements":
        elements = [from_proto(v) for v in transform.append_missing_elements.values]
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING or not isinstance(existing, list):
            existing = []
        result = list(existing)
        for e in elements:
            if not any(compare(e, x) == 0 for x in result):
                result.append(e)
        _set_dotted(new_fields, path, result)
        return new_fields, result

    if which == "remove_all_from_array":
        elements = [from_proto(v) for v in transform.remove_all_from_array.values]
        existing = _get_dotted(new_fields, path)
        if existing is _MISSING or not isinstance(existing, list):
            return new_fields, existing if existing is not _MISSING else None
        result = [x for x in existing if not any(compare(x, e) == 0 for e in elements)]
        _set_dotted(new_fields, path, result)
        return new_fields, result

    raise InvalidArgument(f"unsupported transform: {which}")


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value
