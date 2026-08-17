from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from polymarket_edge_lab.shadow.events import EventEnvelope


class AppendOnlyEventStore:
    """Durable NDJSON event store with one validated in-process writer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._next_sequence, self._file_size, self._record_cache = self._scan_state()

    def _scan_state(self) -> tuple[int, int, list[dict[str, object]]]:
        sequence = 0
        records: list[dict[str, object]] = []
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        raise ValueError(f"blank event record at line {line_number}")
                    value = json.loads(text)
                    if not isinstance(value, dict):
                        raise ValueError(f"event record at line {line_number} must be an object")
                    record_sequence = value.get("sequence")
                    if not isinstance(record_sequence, int):
                        raise ValueError("event record sequence must be an integer")
                    if record_sequence != sequence:
                        raise ValueError(
                            "non-contiguous append-only sequence at "
                            f"{record_sequence}, expected {sequence}"
                        )
                    records.append(value)
                    sequence += 1
        size = self.path.stat().st_size if self.path.exists() else 0
        return sequence, size, records

    def _assert_exclusive_writer_state(self) -> None:
        actual_size = self.path.stat().st_size if self.path.exists() else 0
        if actual_size != self._file_size:
            raise ValueError(
                "event log changed outside this store instance; "
                f"expected size {self._file_size}, found {actual_size}"
            )

    def append(self, event: EventEnvelope) -> None:
        self._assert_exclusive_writer_state()
        expected = self._next_sequence
        if event.sequence != expected:
            raise ValueError(f"expected sequence {expected}, got {event.sequence}")
        record = event.to_record()
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self._next_sequence += 1
        self._file_size = self.path.stat().st_size
        self._record_cache.append(record)

    def next_sequence(self) -> int:
        self._assert_exclusive_writer_state()
        return self._next_sequence

    def end_offset(self) -> int:
        """Return the validated durable byte offset at the current append boundary."""
        self._assert_exclusive_writer_state()
        return self._file_size

    def read_records_from(self, offset: int) -> tuple[list[dict[str, object]], int]:
        """Read only records appended at or after a prior durable byte boundary."""
        self._assert_exclusive_writer_state()
        snapshot_end = self._file_size
        if offset < 0 or offset > snapshot_end:
            raise ValueError(
                f"event-log offset {offset} is outside durable range 0..{snapshot_end}"
            )
        if offset == snapshot_end:
            return [], snapshot_end
        if not self.path.exists():
            if offset != 0:
                raise ValueError("non-zero event-log offset for missing log")
            return [], 0

        records: list[dict[str, object]] = []
        with self.path.open("rb") as handle:
            if offset > 0:
                handle.seek(offset - 1)
                if handle.read(1) != b"\n":
                    raise ValueError(f"event-log offset {offset} is not a record boundary")
            handle.seek(offset)
            while handle.tell() < snapshot_end:
                raw_line = handle.readline()
                if not raw_line or not raw_line.endswith(b"\n"):
                    raise ValueError("event log ended with a partial durable record")
                if handle.tell() > snapshot_end:
                    raise ValueError("event-log record crossed the durable snapshot boundary")
                text = raw_line.decode("utf-8").strip()
                if not text:
                    raise ValueError("blank event record in incremental tail")
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError("incremental event record must be an object")
                records.append(value)
        return records, snapshot_end

    def iter_records(self) -> Iterator[dict[str, object]]:
        """Iterate the validated in-memory record snapshot without reparsing NDJSON."""
        self._assert_exclusive_writer_state()
        yield from self._record_cache
