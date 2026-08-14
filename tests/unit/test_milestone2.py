from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polymarket_edge_lab.analysis.claim_validation import (
    build_claim_results,
    claim_results_to_markdown,
)
from polymarket_edge_lab.analysis.trading_activity import summarize_trading_activity
from polymarket_edge_lab.collectors.windowed import WindowResult, collect_windowed
from polymarket_edge_lab.models.trade import NormalizedTrade
from polymarket_edge_lab.reconstruction.exposure import summarize_exposure
from polymarket_edge_lab.reconstruction.inventory import reconstruct_inventory
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger
from polymarket_edge_lab.reconstruction.market_summary import build_market_summaries
from polymarket_edge_lab.reconstruction.pairing import summarize_pair_accounting
from polymarket_edge_lab.validation.completeness import summarize_window_completeness

ACCOUNT = "0xabc0000000000000000000000000000000000000"


def _trade(
    *,
    trade_id: str,
    market_id: str,
    outcome: str,
    side: str,
    price: str,
    shares: str,
    timestamp: datetime,
) -> NormalizedTrade:
    return NormalizedTrade(
        source="polymarket-data-api",
        source_trade_id=trade_id,
        account=ACCOUNT,
        market_id=market_id,
        asset_id=f"asset-{outcome}",
        timestamp=timestamp,
        outcome=outcome,
        side=side,  # type: ignore[arg-type]
        price=Decimal(price),
        shares=Decimal(shares),
        raw_extra={
            "_raw_page_path": "x.json",
            "_raw_page_hash": "h",
            "_page_offset": 0,
            "_record_index": 0,
        },
    )


def test_ledger_sorted_and_binary_eligibility() -> None:
    t1 = _trade(
        trade_id="2",
        market_id="m1",
        outcome="DOWN",
        side="BUY",
        price="0.55",
        shares="1",
        timestamp=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
    )
    t2 = _trade(
        trade_id="1",
        market_id="m1",
        outcome="UP",
        side="BUY",
        price="0.44",
        shares="1",
        timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )
    ledger = build_canonical_ledger([t1, t2], complete_market_ids={"m1"})
    assert [row.source_trade_id for row in ledger] == ["1", "2"]
    assert all(row.eligible_binary_market for row in ledger)
    assert {row.normalized_outcome_side for row in ledger} == {"UP", "DOWN"}


def test_ambiguous_market_excluded_with_reason() -> None:
    rows = [
        _trade(
            trade_id="a",
            market_id="m2",
            outcome="MAYBE",
            side="BUY",
            price="0.5",
            shares="1",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        _trade(
            trade_id="b",
            market_id="m2",
            outcome="LATER",
            side="BUY",
            price="0.5",
            shares="1",
            timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        ),
    ]
    ledger = build_canonical_ledger(rows, complete_market_ids={"m2"})
    assert all(not row.eligible_binary_market for row in ledger)
    assert all(
        row.market_exclusion_reason == "ambiguous_non_complementary_outcomes" for row in ledger
    )


def test_inventory_weighted_pair_regression_fixture() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(
            trade_id="1",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.44",
            shares="100",
            timestamp=ts,
        ),
        _trade(
            trade_id="2",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.42",
            shares="50",
            timestamp=ts + timedelta(seconds=1),
        ),
        _trade(
            trade_id="3",
            market_id="m1",
            outcome="DOWN",
            side="BUY",
            price="0.53",
            shares="80",
            timestamp=ts + timedelta(seconds=2),
        ),
        _trade(
            trade_id="4",
            market_id="m1",
            outcome="DOWN",
            side="BUY",
            price="0.51",
            shares="70",
            timestamp=ts + timedelta(seconds=3),
        ),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    events = reconstruct_inventory(ledger)["m1"]
    last = events[-1]

    assert last.up_inventory == Decimal("150")
    assert last.down_inventory == Decimal("150")
    assert last.paired_shares == Decimal("150")
    assert last.directional_shares == Decimal("0")
    assert last.up_buy_cost == Decimal("65.00")
    assert last.down_buy_cost == Decimal("78.10")
    assert last.up_weighted_avg_buy_cost == Decimal("0.4333333333333333333333333333")
    assert last.down_weighted_avg_buy_cost == Decimal("0.5206666666666666666666666667")

    pairing = summarize_pair_accounting("m1", events)
    assert pairing.weighted_pair_cost == Decimal("0.954")
    assert pairing.weighted_gross_pair_edge == Decimal("0.046")


def test_inventory_sell_reduces_and_partial_pairing() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(
            trade_id="1",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.40",
            shares="10",
            timestamp=ts,
        ),
        _trade(
            trade_id="2",
            market_id="m1",
            outcome="DOWN",
            side="BUY",
            price="0.60",
            shares="6",
            timestamp=ts + timedelta(seconds=1),
        ),
        _trade(
            trade_id="3",
            market_id="m1",
            outcome="UP",
            side="SELL",
            price="0.50",
            shares="3",
            timestamp=ts + timedelta(seconds=2),
        ),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    events = reconstruct_inventory(ledger)["m1"]
    assert events[1].paired_shares == Decimal("6")
    assert events[2].up_inventory == Decimal("7")
    assert events[2].paired_shares == Decimal("6")
    assert events[2].directional_side == "UP"
    assert events[2].directional_shares == Decimal("1")


def test_fifo_pair_cost_sensitivity_present() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(
            trade_id="1",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.40",
            shares="3",
            timestamp=ts,
        ),
        _trade(
            trade_id="2",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.50",
            shares="3",
            timestamp=ts + timedelta(seconds=1),
        ),
        _trade(
            trade_id="3",
            market_id="m1",
            outcome="DOWN",
            side="BUY",
            price="0.50",
            shares="6",
            timestamp=ts + timedelta(seconds=2),
        ),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    events = reconstruct_inventory(ledger)["m1"]
    pairing = summarize_pair_accounting("m1", events)
    assert pairing.fifo_pair_cost is not None
    assert pairing.fifo_gross_pair_edge == Decimal("1") - pairing.fifo_pair_cost


def test_exposure_metrics() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(
            trade_id="1",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.4",
            shares="10",
            timestamp=ts,
        ),
        _trade(
            trade_id="2",
            market_id="m1",
            outcome="DOWN",
            side="BUY",
            price="0.4",
            shares="5",
            timestamp=ts + timedelta(seconds=1),
        ),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    events = reconstruct_inventory(ledger)["m1"]
    exposure = summarize_exposure(events)
    assert exposure.paired_share_event_ratio is not None
    assert exposure.directional_share_event_ratio is not None
    assert exposure.paired_end_of_market_ratio == Decimal("0.5")
    assert exposure.directional_end_of_market_ratio == Decimal("0.5")


def test_incomplete_history_markets_excluded_from_pair_claims() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(
            trade_id="1",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.4",
            shares="1",
            timestamp=ts,
        ),
        _trade(
            trade_id="2",
            market_id="m1",
            outcome="DOWN",
            side="BUY",
            price="0.4",
            shares="1",
            timestamp=ts + timedelta(seconds=1),
        ),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids=set())
    activity = summarize_trading_activity(ledger)
    inventory = reconstruct_inventory(ledger)
    all_events = [event for rows in inventory.values() for event in rows]
    exposure = summarize_exposure(all_events)
    summaries = build_market_summaries(ledger, inventory, {})
    claims = build_claim_results(activity=activity, exposure=exposure, market_summaries=summaries)
    pair_cost = [c for c in claims if c.claim == "98.43¢ average pair cost"][0]
    assert pair_cost.measured_value == "None"
    assert pair_cost.status == "inconclusive"


def test_claim_report_markdown_deterministic() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(
            trade_id="1",
            market_id="m1",
            outcome="UP",
            side="BUY",
            price="0.5",
            shares="1",
            timestamp=ts,
        ),
        _trade(
            trade_id="2",
            market_id="m1",
            outcome="DOWN",
            side="BUY",
            price="0.5",
            shares="1",
            timestamp=ts + timedelta(seconds=1),
        ),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    inventory = reconstruct_inventory(ledger)
    summaries = build_market_summaries(
        ledger,
        inventory,
        {"m1": summarize_pair_accounting("m1", inventory["m1"])},
    )
    claims = build_claim_results(
        activity=summarize_trading_activity(ledger),
        exposure=summarize_exposure([event for rows in inventory.values() for event in rows]),
        market_summaries=summaries,
    )
    md = claim_results_to_markdown(claims)
    assert "| Public claim | Measured result |" in md
    assert "98.43¢ average pair cost" in md


class _SubdivideCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    async def fetch_page(
        self,
        *,
        account: str,
        offset: int,
        limit: int,
        window_start: int | None = None,
        window_end: int | None = None,
    ) -> tuple[bytes, list[dict[str, object]]]:
        assert window_start is not None and window_end is not None
        self.calls.append((window_start, window_end, offset))
        duration = window_end - window_start
        if duration > 10 and offset <= 10000:
            rec = {
                "id": f"{window_start}-{offset}",
                "conditionId": "m1",
                "asset": "a",
                "side": "BUY",
                "size": Decimal("1"),
                "price": Decimal("0.5"),
                "timestamp": 1_700_000_000,
                "outcome": "UP",
                "proxyWallet": ACCOUNT,
            }
            records = [rec] * limit
        else:
            records = []
        import json

        return json.dumps(records, default=str).encode(), records

    def endpoint_url(self, **_: object) -> str:
        return "https://data-api.polymarket.com/trades"


def test_collect_windowed_subdivision_and_unresolved() -> None:
    collector = _SubdivideCollector()
    results = asyncio.run(async_collect_windowed(collector))
    assert any(r.ceiling_hit for r in results)
    assert any((r.window_end - r.window_start) <= 10 for r in results)
    summary = summarize_window_completeness(results)
    assert summary.windows_unresolved > 0


async def async_collect_windowed(collector: _SubdivideCollector) -> list[WindowResult]:
    return await collect_windowed(
        collector,  # type: ignore[arg-type]
        account=ACCOUNT,
        global_start=0,
        global_end=40,
        window_seconds=40,
        page_size=2000,
        dry_run=True,
        min_window_seconds=10,
    )
