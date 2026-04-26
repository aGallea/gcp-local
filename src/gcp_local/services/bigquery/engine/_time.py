"""Timestamp helpers shared across the BigQuery service."""

import datetime as dt


def now_epoch_ms_str() -> str:
    """Return current time as milliseconds-since-epoch string (BQ REST API format)."""
    return str(int(dt.datetime.now(tz=dt.UTC).timestamp() * 1000))
