from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from polymarket_edge_lab.analysis.bounded_pair_claim import fully_contained_btc_5m_market_ids
from polymarket_edge_lab.analysis.btc_features import BtcCandle
from polymarket_edge_lab.analysis.stage3g_pre_event import audit_pre_event_rows, build_pre_event_rows
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger
from polymarket_edge_lab.storage.normalized import load_duckdb


def materialize_pre_event_window(
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
    rows = build_pre_event_rows(
        ledger,
        complete_market_ids=complete_ids,
        btc_candles=btc_candles,
        window_id=window_id,
    )
    audit = audit_pre_event_rows(rows)
    diagnostics = {
        "window_id": window_id,
        "trade_count": len(trades),
        "complete_market_count": len(complete_ids),
        "panel_row_count": len(rows),
        "favorable_ratio_unweighted": (
            sum(bool(row["favorable"]) for row in rows) / len(rows) if rows else None
        ),
        "leakage_audit": audit,
    }
    return rows, diagnostics


def write_pre_event_panel(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
