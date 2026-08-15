from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from polymarket_edge_lab.analysis.bounded_pair_claim import (
    btc_5m_market_start,
    fully_contained_btc_5m_market_ids,
)
from polymarket_edge_lab.analysis.btc_features import BtcCandle, build_btc_features
from polymarket_edge_lab.analysis.pair_sensitivity import pair_events_by_method
from polymarket_edge_lab.analysis.regime_features import build_regime_features
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger
from polymarket_edge_lab.storage.normalized import load_duckdb


def _numeric(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def materialize_window(
    *,
    window_id: str,
    account: str,
    duckdb_path: Path,
    collection_start: int,
    collection_end: int,
    btc_candles: list[BtcCandle],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trades = load_duckdb(duckdb_path, account=account)
    complete_ids = fully_contained_btc_5m_market_ids(
        trades,
        collection_start=collection_start,
        collection_end=collection_end,
    )
    ledger = build_canonical_ledger(trades, complete_market_ids=complete_ids)
    events_by_method, sell_markets = pair_events_by_method(
        ledger,
        complete_market_ids=complete_ids,
    )
    fifo_events = events_by_method["fifo"]
    regime_rows = build_regime_features(
        ledger,
        fifo_events,
        complete_market_ids=complete_ids,
    )

    rows: list[dict[str, Any]] = []
    for regime in regime_rows:
        start = btc_5m_market_start(regime.slug)
        btc = build_btc_features(
            btc_candles,
            event_epoch=regime.formed_at_epoch,
            market_start_epoch=start,
        )
        row = {key: _numeric(value) for key, value in regime.to_dict().items()}
        for key, value in asdict(btc).items():
            if key == "event_epoch":
                continue
            row[f"btc_{key}"] = _numeric(value)
        row["window_id"] = window_id
        rows.append(row)

    btc_columns = [key for key in rows[0] if key.startswith("btc_")] if rows else []
    coverage = {
        key: sum(row.get(key) is not None for row in rows) / len(rows) if rows else 0.0
        for key in btc_columns
    }
    diagnostics = {
        "window_id": window_id,
        "trade_count": len(trades),
        "complete_market_count": len(complete_ids),
        "sell_excluded_market_count": len(sell_markets),
        "fifo_event_count": len(fifo_events),
        "panel_row_count": len(rows),
        "btc_feature_coverage": coverage,
        "favorable_ratio_unweighted": (
            sum(bool(row["favorable"]) for row in rows) / len(rows) if rows else None
        ),
    }
    return rows, diagnostics


def write_panel_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
