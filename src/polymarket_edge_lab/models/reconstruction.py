from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

OutcomeSide = Literal["UP", "DOWN"]


@dataclass(frozen=True)
class LedgerEntry:
    source_trade_id: str
    account: str
    market_id: str
    asset_id: str
    outcome: str
    side: Literal["BUY", "SELL"]
    timestamp: datetime
    price: Decimal
    shares: Decimal
    notional: Decimal
    transaction_hash: str | None
    outcome_index: int | None
    slug: str | None
    event_slug: str | None
    title: str | None
    raw_page_path: str | None
    raw_page_hash: str | None
    page_offset: int | None
    record_index: int | None
    market_sequence_number: int
    fill_sequence_number: int
    eligible_binary_market: bool
    market_exclusion_reason: str | None
    normalized_outcome_side: OutcomeSide | None
    outcome_side_reason: str | None


@dataclass(frozen=True)
class InventoryEvent:
    market_id: str
    source_trade_id: str
    timestamp: datetime
    side: Literal["BUY", "SELL"]
    outcome_side: OutcomeSide
    price: Decimal
    shares: Decimal
    up_inventory: Decimal
    down_inventory: Decimal
    paired_shares: Decimal
    directional_side: OutcomeSide | None
    directional_shares: Decimal
    up_buy_cost: Decimal
    down_buy_cost: Decimal
    up_weighted_avg_buy_cost: Decimal | None
    down_weighted_avg_buy_cost: Decimal | None
    inventory_anomaly_reason: str | None = None


@dataclass(frozen=True)
class PairAccountingSummary:
    market_id: str
    gross_pair_formation_shares: Decimal
    ending_paired_shares: Decimal
    weighted_pair_cost: Decimal | None
    weighted_gross_pair_edge: Decimal | None
    fifo_pair_cost: Decimal | None
    fifo_gross_pair_edge: Decimal | None


@dataclass(frozen=True)
class ExposureSummary:
    paired_share_event_ratio: Decimal | None
    directional_share_event_ratio: Decimal | None
    paired_end_of_market_ratio: Decimal | None
    directional_end_of_market_ratio: Decimal | None
    paired_dollar_cost_ratio: Decimal | None
    directional_dollar_cost_ratio: Decimal | None


@dataclass(frozen=True)
class MarketSummary:
    market_id: str
    first_trade_timestamp: datetime
    last_trade_timestamp: datetime
    fill_count: int
    total_buy_notional: Decimal
    total_sell_notional: Decimal
    ending_up_shares: Decimal
    ending_down_shares: Decimal
    max_paired_shares: Decimal
    ending_paired_shares: Decimal
    ending_directional_side: OutcomeSide | None
    ending_directional_shares: Decimal
    weighted_avg_up_cost: Decimal | None
    weighted_avg_down_cost: Decimal | None
    weighted_pair_cost: Decimal | None
    weighted_gross_pair_edge: Decimal | None
    fifo_pair_cost: Decimal | None
    fifo_gross_pair_edge: Decimal | None
    history_complete: bool
    validation_warnings: list[str] = field(default_factory=list)
