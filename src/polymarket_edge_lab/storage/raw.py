"""Immutable raw payload storage helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_raw_page(
    records: list[dict[str, Any]],
    *,
    output_dir: Path,
    account: str,
    offset: int,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = output_dir / f"{account}_{offset:09d}_{stamp}.json"
    path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
    return path
