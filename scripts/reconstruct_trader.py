#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from polymarket_edge_lab.analysis.trading_activity import summarize_trading_activity
from polymarket_edge_lab.config.targets import load_targets
from polymarket_edge_lab.models.reconstruction import InventoryEvent, LedgerEntry, MarketSummary
from polymarket_edge_lab.reconstruction.exposure import summarize_exposure
from polymarket_edge_lab.reconstruction.inventory import reconstruct_inventory
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger
from polymarket_edge_lab.reconstruction.market_summary import build_market_summaries
from polymarket_edge_lab.reconstruction.pairing import summarize_pair_accounting
from polymarket_edge_lab.storage.normalized import load_duckdb


def _serialize(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def _as_json_rows(
    rows: list[LedgerEntry] | list[InventoryEvent] | list[MarketSummary],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        data = asdict(row)
        out.append({k: _serialize(v) for k, v in data.items()})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct milestone-2 forensic ledger")
    parser.add_argument("--target", default="nagi777")
    parser.add_argument("--account", default=None)
    parser.add_argument("--duckdb-path", type=Path, default=Path("data/polymarket_edge_lab.duckdb"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument(
        "--history-complete",
        action="store_true",
        help="Mark history complete for all markets in this run.",
    )
    args = parser.parse_args()

    targets = load_targets(Path("config/targets.json"))
    target_meta = targets.get(args.target)
    account = args.account or (target_meta.proxy_wallet if target_meta else None)
    if not account:
        raise SystemExit(
            "No account configured. Provide --account or set a verified "
            "proxy_wallet in config/targets.json."
        )

    trades = load_duckdb(args.duckdb_path, account=account)
    if not trades:
        raise SystemExit(f"No trades found in {args.duckdb_path} for account={account}")

    market_ids = {t.market_id for t in trades}
    complete_market_ids = market_ids if args.history_complete else set()

    ledger = build_canonical_ledger(trades, complete_market_ids=complete_market_ids)
    inventory = reconstruct_inventory(ledger)
    pairings = {mid: summarize_pair_accounting(mid, events) for mid, events in inventory.items()}
    summaries = build_market_summaries(ledger, inventory, pairings)
    activity = summarize_trading_activity(ledger)
    exposure = summarize_exposure([e for events in inventory.values() for e in events])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{args.target}_{stamp}"

    (args.output_dir / f"{prefix}_ledger.json").write_text(
        json.dumps(_as_json_rows(ledger), indent=2), encoding="utf-8"
    )
    (args.output_dir / f"{prefix}_inventory_events.json").write_text(
        json.dumps(
            {k: _as_json_rows(v) for k, v in inventory.items()},
            indent=2,
            default=_serialize,
        ),
        encoding="utf-8",
    )
    (args.output_dir / f"{prefix}_market_summaries.json").write_text(
        json.dumps(_as_json_rows(summaries), indent=2), encoding="utf-8"
    )
    (args.output_dir / f"{prefix}_reconstruction_meta.json").write_text(
        json.dumps(
            {
                "target": args.target,
                "account": account,
                "history_complete": args.history_complete,
                "trades": activity.total_trades,
                "active_hours": activity.active_hours,
                "trades_per_active_hour": _serialize(activity.trades_per_active_hour),
                "average_trade_notional": _serialize(activity.average_trade_notional),
                "paired_share_event_ratio": _serialize(exposure.paired_share_event_ratio),
                "directional_share_event_ratio": _serialize(exposure.directional_share_event_ratio),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
