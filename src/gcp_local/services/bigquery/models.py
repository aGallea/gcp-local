"""Domain records for BigQuery resources.

Extended in Task 4 with DatasetRecord/TableRecord/JobRecord.
"""

from dataclasses import dataclass
from typing import Literal

FieldMode = Literal["NULLABLE", "REQUIRED", "REPEATED"]


@dataclass(frozen=True)
class FieldSchema:
    name: str
    type: str
    mode: FieldMode
    fields: list["FieldSchema"] | None
