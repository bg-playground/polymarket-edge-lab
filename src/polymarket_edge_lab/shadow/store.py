from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from polymarket_edge_lab.shadow.events import EventEnvelope


class AppendOnlyEventStore:
    """Durable newline-delimited JSON event store with monotonic per-file sequence checks."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: EventEnvelope) -> None:
        expected = self.next_sequence()
        if event.sequence != expected:
            raise ValueError(f"expected sequence {expected}, got {event.sequence}")
        line = json.dumps(event.to_record(), sort_keys=True, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def next_sequence(self) -> int:
        sequence = 0
        for record in self.iter_records():
            value = record.get("sequence")
            if not isinstance(value, int):
                raise ValueError("event record sequence must be an integer")
            if value != sequence:
                raise ValueError(
                    f"non-contiguous append-only sequence at {value}, expected {sequence}"
                )
            sequence += 1
        return sequence

    def iter_records(self) -> Iterator[dict[str, object]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    raise ValueError(f"blank event record at line {line_number}")
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError(f"event record at line {line_number} must be an object")
                yield value
