from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from polymarket_edge_lab.analysis.btc_features import BtcCandle

COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"


@dataclass(frozen=True)
class BtcReferenceProvenance:
    provider: str
    symbol: str
    endpoint: str
    granularity_seconds: int
    requested_start_epoch: int
    requested_end_epoch: int
    observed_start_epoch: int | None
    observed_end_epoch: int | None
    retrieved_at: str
    raw_sha256: str
    candle_count: int


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def _parse_rows(payload: Any) -> list[BtcCandle]:
    if not isinstance(payload, list):
        raise ValueError("Coinbase candle response must be a list")
    candles: list[BtcCandle] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError("Unexpected Coinbase candle row")
        candles.append(
            BtcCandle(
                open_epoch=int(row[0]),
                low=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                open=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
            )
        )
    return sorted(candles, key=lambda candle: candle.open_epoch)


def collect_coinbase_btc_usd(
    *,
    start_epoch: int,
    end_epoch: int,
    raw_path: Path,
    granularity_seconds: int = 60,
) -> tuple[list[BtcCandle], BtcReferenceProvenance]:
    """Collect public Coinbase BTC-USD candles in bounded chunks with raw preservation."""
    if end_epoch <= start_epoch:
        raise ValueError("end_epoch must be greater than start_epoch")
    if granularity_seconds != 60:
        raise ValueError("Stage 3B currently supports Coinbase 60-second candles only")

    # Coinbase caps a candle request at 300 buckets. Use 240-minute chunks with overlap.
    chunk_seconds = 240 * granularity_seconds
    raw_pages: list[dict[str, object]] = []
    by_epoch: dict[int, BtcCandle] = {}
    cursor = start_epoch - 180
    stop = end_epoch
    with httpx.Client(timeout=30.0, headers={"User-Agent": "polymarket-edge-lab/0.1"}) as client:
        while cursor < stop:
            chunk_end = min(cursor + chunk_seconds, stop)
            params = {
                "start": _iso(cursor),
                "end": _iso(chunk_end),
                "granularity": granularity_seconds,
            }
            response = client.get(COINBASE_CANDLES_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            raw_pages.append({"params": params, "payload": payload})
            for candle in _parse_rows(payload):
                by_epoch[candle.open_epoch] = candle
            cursor = chunk_end

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = json.dumps(raw_pages, sort_keys=True, separators=(",", ":")).encode()
    raw_path.write_bytes(raw_bytes)
    candles = sorted(by_epoch.values(), key=lambda candle: candle.open_epoch)
    provenance = BtcReferenceProvenance(
        provider="Coinbase Exchange public REST API",
        symbol="BTC-USD",
        endpoint=COINBASE_CANDLES_URL,
        granularity_seconds=granularity_seconds,
        requested_start_epoch=start_epoch,
        requested_end_epoch=end_epoch,
        observed_start_epoch=candles[0].open_epoch if candles else None,
        observed_end_epoch=candles[-1].open_epoch if candles else None,
        retrieved_at=datetime.now(tz=UTC).isoformat(),
        raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        candle_count=len(candles),
    )
    return candles, provenance


def write_provenance(path: Path, provenance: BtcReferenceProvenance) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(asdict(provenance), indent=2, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8")
