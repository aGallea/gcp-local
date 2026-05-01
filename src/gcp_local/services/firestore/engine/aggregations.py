"""Firestore aggregation engine — COUNT, SUM, AVG over a list of DocumentRecords."""

from __future__ import annotations

from typing import Any

from gcp_local.generated.google.firestore.v1 import query_pb2

# Re-export from query.py so callers only need one import.
from gcp_local.services.firestore.engine.query import _MISSING, _field
from gcp_local.services.firestore.models import DocumentRecord

__all__ = ["aggregate"]


def aggregate(
    records: list[DocumentRecord],
    aggregations: list[query_pb2.StructuredAggregationQuery.Aggregation],
) -> dict[str, Any]:
    """Compute aggregation results over *records*.

    Returns a mapping of alias -> Python value (int, float, or None for empty avg).

    Rules:
    - alias defaults to the operator name when the client doesn't supply one.
    - COUNT: integer count, clamped by up_to when present.
    - SUM: sum of numeric (non-bool) field values; result is int when all values
      are integers, float if any are float.  Non-numeric and bool values are skipped.
    - AVG: float average of numeric non-bool values; None when no values matched.
    """
    out: dict[str, Any] = {}
    for agg in aggregations:
        which = agg.WhichOneof("operator")
        alias = agg.alias or which  # empty alias → operator name

        if which == "count":
            n = len(records)
            if agg.count.HasField("up_to"):
                n = min(n, agg.count.up_to.value)
            out[alias] = n

        elif which == "sum":
            field_path = agg.sum.field.field_path
            total: int | float = 0
            seen_double = False
            for rec in records:
                v = _field(rec, field_path)
                if v is _MISSING or isinstance(v, bool):
                    continue
                if isinstance(v, float):
                    seen_double = True
                if isinstance(v, (int, float)):
                    total += v
            out[alias] = float(total) if seen_double else int(total)

        elif which == "avg":
            field_path = agg.avg.field.field_path
            running_total = 0.0
            count = 0
            for rec in records:
                v = _field(rec, field_path)
                if v is _MISSING or isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)):
                    running_total += v
                    count += 1
            out[alias] = (running_total / count) if count else None

    return out
