"""Small validation-report primitives for Milestone 1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationReport:
    input_records: int
    valid_records: int
    duplicate_records: int
    invalid_records: int

    @property
    def is_clean(self) -> bool:
        return self.invalid_records == 0 and self.duplicate_records == 0
