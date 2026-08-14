#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from polymarket_edge_lab.analysis.claim_validation import (
    build_claim_results,
    claim_results_to_json,
    claim_results_to_markdown,
)
from polymarket_edge_lab.analysis.trading_activity import summarize_trading_activity
from polymarket_edge_lab.config.targets import load_targets
from polymarket_edge_lab.reconstruction.exposure import summarize_exposure
from polymarket_edge_lab.reconstruction.inventory import reconstruct_inventory
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger
from polymarket_edge_lab.reconstruction.market_summary import build_market_summaries
from polymarket_edge_lab.reconstruction.pairing import summarize_pair_accounting
from polymarket_edge_lab.storage.normalized import load_duckdb


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate milestone-2 claim validation reports")
    parser.add_argument("--target", default="nagi777")
    parser.add_argument("--account", default=None)
    parser.add_argument("--duckdb-path", type=Path, default=Path("data/polymarket_edge_lab.duckdb"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--history-complete", action="store_true")
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
    market_ids = {t.market_id for t in trades}
    complete_market_ids = market_ids if args.history_complete else set()
    ledger = build_canonical_ledger(trades, complete_market_ids=complete_market_ids)
    inventory = reconstruct_inventory(ledger)
    pairings = {mid: summarize_pair_accounting(mid, events) for mid, events in inventory.items()}
    market_summaries = build_market_summaries(ledger, inventory, pairings)
    activity = summarize_trading_activity(ledger)
    exposure = summarize_exposure([event for rows in inventory.values() for event in rows])

    claims = build_claim_results(
        activity=activity, exposure=exposure, market_summaries=market_summaries
    )
    out_json = claim_results_to_json(claims)
    out_md = claim_results_to_markdown(claims)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"{args.target}_claim_validation.json"
    md_path = args.output_dir / f"{args.target}_claim_validation.md"
    json_path.write_text(json.dumps(out_json, indent=2), encoding="utf-8")
    md_path.write_text(out_md, encoding="utf-8")


if __name__ == "__main__":
    main()
