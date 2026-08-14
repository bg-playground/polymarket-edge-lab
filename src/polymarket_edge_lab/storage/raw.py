"""Immutable raw payload storage with atomic create-only writes, content hashing,
and a JSON manifest for resumability.

Raw files are NEVER overwritten. Each stored page is uniquely identified by its
content hash. A sidecar manifest file tracks completed pages so the collector
can skip pages it has already saved.

Manifest entries carry optional ``window_start`` and ``window_end`` (epoch
seconds) fields so windowed pagination can resume at a specific
``(window_start, window_end, offset)`` triplet rather than just an offset.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_raw_page(
    raw_bytes: bytes,
    *,
    output_dir: Path,
    account: str,
    offset: int,
    limit: int,
    endpoint_url: str = "",
    window_start: int | None = None,
    window_end: int | None = None,
) -> tuple[Path, str]:
    """Write raw API response bytes to an immutable file.

    The file is written atomically (rename from a temp file in the same
    directory) so a partial write is never visible.  Returns the path and
    SHA-256 hex digest of the stored bytes.

    Parameters
    ----------
    window_start:
        Optional lower bound of the time window in epoch **seconds**.  Stored
        in the manifest for windowed-pagination provenance and resumability.
    window_end:
        Optional upper bound of the time window in epoch **seconds**.

    Raises FileExistsError if a file with the same content hash already
    exists (content-addressed deduplication).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    content_hash = _sha256_hex(raw_bytes)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{account}_{offset:09d}_{stamp}_{content_hash[:12]}.json"
    dest = output_dir / filename

    # Atomic create-only write via temp file + rename.
    fd, tmp_path = tempfile.mkstemp(dir=output_dir, prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw_bytes)
        # Rename is atomic on POSIX.  On Windows this may raise if dest exists,
        # which is the desired behaviour (immutability).
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Record metadata sidecar.
    _append_manifest(
        output_dir=output_dir,
        account=account,
        offset=offset,
        limit=limit,
        filename=filename,
        content_hash=content_hash,
        collected_at=stamp,
        endpoint_url=endpoint_url,
        record_count=len(json.loads(raw_bytes)) if raw_bytes.strip() else 0,
        window_start=window_start,
        window_end=window_end,
    )

    return dest, content_hash


def _append_manifest(
    *,
    output_dir: Path,
    account: str,
    offset: int,
    limit: int,
    filename: str,
    content_hash: str,
    collected_at: str,
    endpoint_url: str,
    record_count: int,
    window_start: int | None = None,
    window_end: int | None = None,
) -> None:
    manifest_path = output_dir / f"{account}_manifest.jsonl"
    entry: dict[str, Any] = {
        "account": account,
        "offset": offset,
        "limit": limit,
        "filename": filename,
        "content_hash": content_hash,
        "collected_at": collected_at,
        "endpoint_url": endpoint_url,
        "record_count": record_count,
    }
    if window_start is not None:
        entry["window_start"] = window_start
    if window_end is not None:
        entry["window_end"] = window_end
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def load_manifest(
    output_dir: Path,
    account: str,
) -> list[dict[str, Any]]:
    """Return all manifest entries for *account* from *output_dir*."""
    manifest_path = output_dir / f"{account}_manifest.jsonl"
    if not manifest_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with manifest_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def completed_offsets(output_dir: Path, account: str) -> set[int]:
    """Return the set of offsets already stored for *account* (non-windowed only)."""
    return {
        int(e["offset"])
        for e in load_manifest(output_dir, account)
        if e.get("window_start") is None and e.get("window_end") is None
    }


def completed_window_offsets(
    output_dir: Path,
    account: str,
) -> dict[tuple[int, int], set[int]]:
    """Return a mapping of ``(window_start, window_end)`` → set of completed offsets.

    Only entries that have both ``window_start`` and ``window_end`` are included.
    Use this to determine which ``(window, offset)`` pairs can be skipped during
    a windowed-pagination resume.
    """
    result: dict[tuple[int, int], set[int]] = {}
    for entry in load_manifest(output_dir, account):
        ws = entry.get("window_start")
        we = entry.get("window_end")
        if ws is not None and we is not None:
            key = (int(ws), int(we))
            result.setdefault(key, set()).add(int(entry["offset"]))
    return result
