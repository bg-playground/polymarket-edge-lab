from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polymarket_edge_lab.analysis.stage3g_pre_event import audit_pre_event_rows, build_pre_event_rows
from polymarket_edge_lab.models.reconstruction import LedgerEntry


def _fill(sequence: int, epoch: int, side: str, price: str, shares: str) -> LedgerEntry:
    return LedgerEntry(
        source_trade_id=f"trade-{sequence}",
        account="acct",
        market_id="market",
        asset_id=f"asset-{side}",
        outcome=side,
        side="BUY",
        timestamp=datetime.fromtimestamp(epoch, tz=timezone.utc),
        price=Decimal(price),
        shares=Decimal(shares),
        notional=Decimal(price) * Decimal(shares),
        transaction_hash=f"tx-{sequence}",
        outcome_index=0 if side == "UP" else 1,
        slug=None,
        event_slug=None,
        title=None,
        raw_page_path=None,
        raw_page_hash=None,
        page_offset=0,
        record_index=sequence,
        market_sequence_number=sequence,
        fill_sequence_number=sequence,
        eligible_binary_market=True,
        market_exclusion_reason=None,
        normalized_outcome_side=side,  # type: ignore[arg-type]
        outcome_side_reason=None,
    )


def test_target_fill_does_not_mutate_its_own_snapshot() -> None:
    ledger = [
        _fill(1, 100, "UP", "0.40", "5"),
        _fill(2, 101, "DOWN", "0.50", "5"),
    ]

    rows = build_pre_event_rows(
        ledger,
        complete_market_ids={"market"},
        btc_candles=[],
        window_id="window",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["up_inventory"] == 5.0
    assert row["down_inventory"] == 0.0
    assert row["fill_count_15s"] == 1
    assert row["same_second_fill_count"] == 0
    assert row["pair_cost"] == 0.9
    assert row["prediction_fill_sequence"] == 2
    assert row["max_prior_fill_sequence"] == 1
    assert audit_pre_event_rows(rows)["passed"] is True
