from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TargetMetadata:
    nickname: str
    proxy_wallet: str | None
    verification_source: str
    verification_date_utc: str | None
    verification_status: str


def load_targets(path: Path) -> dict[str, TargetMetadata]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, TargetMetadata] = {}
    for key, row in payload.get("targets", {}).items():
        out[key] = TargetMetadata(
            nickname=str(row["nickname"]),
            proxy_wallet=row.get("proxy_wallet"),
            verification_source=str(row.get("verification_source", "")),
            verification_date_utc=row.get("verification_date_utc"),
            verification_status=str(row.get("verification_status", "unverified")),
        )
    return out
