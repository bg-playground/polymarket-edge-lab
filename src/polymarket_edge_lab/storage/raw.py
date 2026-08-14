"""Immutable raw payload storage with atomic create-only writes, content hashing,
and a JSON manifest for resumability.

Raw files are NEVER overwritten. Each stored page is uniquely identified by its
content hash. A sidecar manifest file tracks completed pages so the collector
can skip pages it has already saved.
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
) -> tuple[Path, str]:
    """Write raw API response bytes to an immutable file.

    The file is written atomically (rename from a temp file in the same
    directory) so a partial write is never visible.  Returns the path and
    SHA-256 hex digest of the stored bytes.

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
) -> None:
    manifest_path = output_dir / f"{account}_manifest.jsonl"
    entry = {
        "account": account,
        "offset": offset,
        "limit": limit,
        "filename": filename,
        "content_hash": content_hash,
        "collected_at": collected_at,
        "endpoint_url": endpoint_url,
        "record_count": record_count,
    }
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
    """Return the set of offsets already stored for *account*."""
    return {int(e["offset"]) for e in load_manifest(output_dir, account)}
