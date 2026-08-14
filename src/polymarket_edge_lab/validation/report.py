"""Small validation-report primitives for Milestone 1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ValidationReport:
    input_records: int
    valid_records: int
    duplicate_records: int
    invalid_records: int
    missing_required_fields: int = 0
    earliest_timestamp: datetime | None = None
    latest_timestamp: datetime | None = None

    @property
    def is_clean(self) -> bool:
        return self.invalid_records == 0 and self.duplicate_records == 0

    def summary(self) -> str:
        lines = [
            "=== Validation Report ===",
            f"  Total input records  : {self.input_records}",
            f"  Normalized (valid)   : {self.valid_records}",
            f"  Rejected (invalid)   : {self.invalid_records}",
            f"  Duplicates           : {self.duplicate_records}",
            f"  Missing required     : {self.missing_required_fields}",
            f"  Earliest timestamp   : {self.earliest_timestamp}",
            f"  Latest timestamp     : {self.latest_timestamp}",
            f"  Clean                : {self.is_clean}",
        ]
        return "\n".join(lines)


def build_report(
    *,
    input_records: int,
    valid_records: int,
    duplicate_records: int,
    invalid_records: int,
    missing_required_fields: int,
    timestamps: list[datetime],
) -> ValidationReport:
    earliest = min(timestamps) if timestamps else None
    latest = max(timestamps) if timestamps else None
    return ValidationReport(
        input_records=input_records,
        valid_records=valid_records,
        duplicate_records=duplicate_records,
        invalid_records=invalid_records,
        missing_required_fields=missing_required_fields,
        earliest_timestamp=earliest,
        latest_timestamp=latest,
    )
