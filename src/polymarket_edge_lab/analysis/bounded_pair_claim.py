from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from polymarket_edge_lab.models.reconstruction import LedgerEntry
from polymarket_edge_lab.models.trade import NormalizedTrade

ZERO = Decimal("0")
ONE = Decimal("1")
_BTC_5M_RE = re.compile(r"^btc-updown-5m-(\d+)$")
TieBreak = Literal["canonical", "price_asc", "price_desc"]


@dataclass(frozen=True)
class PairFormationEvent:
    market_id: str
    formed_at: datetime
    paired_shares: Decimal
    up_price: Decimal
    down_price: Decimal
    pair_cost: Decimal
    lag_seconds: int


@dataclass(frozen=True)
class PairFormationSummary:
    market_count: int
    fill_count: int
    pair_fragment_count: int
    paired_shares: Decimal
    weighted_pair_cost: Decimal | None
    weighted_gross_pair_edge: Decimal | None
    paired_shares_below_one: Decimal
    below_one_ratio: Decimal | None
    zero_lag_paired_shares: Decimal
    zero_lag_ratio: Decimal | None
    excluded_sell_markets: tuple[str, ...]


def btc_5m_market_start(slug: str | None) -> int | None:
    if not slug:
        return None
    match = _BTC_5M_RE.fullmatch(slug)
    return int(match.group(1)) if match else None


def fully_contained_btc_5m_market_ids(
    trades: list[NormalizedTrade], *, collection_start: int, collection_end: int
) -> set[str]:
    complete: set[str] = set()
    for trade in trades:
        market_start = btc_5m_market_start(trade.slug)
        if market_start is None:
            continue
        if collection_start <= market_start and market_start + 300 <= collection_end:
            complete.add(trade.market_id)
    return complete


def _sort_key(row: LedgerEntry, tie_break: TieBreak) -> tuple[object, ...]:
    if tie_break == "price_asc":
        return (row.timestamp, row.price, row.fill_sequence_number)
    if tie_break == "price_desc":
        return (row.timestamp, -row.price, row.fill_sequence_number)
    return (row.timestamp, row.fill_sequence_number)


def _pair_one_market(rows: list[LedgerEntry], *, tie_break: TieBreak) -> list[PairFormationEvent]:
    unmatched: dict[str, deque[tuple[Decimal, Decimal, datetime]]] = {
        "UP": deque(),
        "DOWN": deque(),
    }
    events: list[PairFormationEvent] = []

    for row in sorted(rows, key=lambda item: _sort_key(item, tie_break)):
        side = row.normalized_outcome_side
        if side not in {"UP", "DOWN"} or row.side != "BUY":
            continue
        opposite = "DOWN" if side == "UP" else "UP"
        remaining = row.shares

        while remaining > ZERO and unmatched[opposite]:
            opposite_qty, opposite_price, opposite_ts = unmatched[opposite][0]
            formed = min(remaining, opposite_qty)
            up_price = row.price if side == "UP" else opposite_price
            down_price = row.price if side == "DOWN" else opposite_price
            lag_seconds = max(0, int((row.timestamp - opposite_ts).total_seconds()))
            events.append(
                PairFormationEvent(
                    market_id=row.market_id,
                    formed_at=row.timestamp,
                    paired_shares=formed,
                    up_price=up_price,
                    down_price=down_price,
                    pair_cost=up_price + down_price,
                    lag_seconds=lag_seconds,
                )
            )
            remaining -= formed
            opposite_qty -= formed
            if opposite_qty == ZERO:
                unmatched[opposite].popleft()
            else:
                unmatched[opposite][0] = (opposite_qty, opposite_price, opposite_ts)

        if remaining > ZERO:
            unmatched[side].append((remaining, row.price, row.timestamp))

    return events


def summarize_chronological_pair_formation(
    ledger: list[LedgerEntry],
    *,
    complete_market_ids: set[str],
    tie_break: TieBreak = "canonical",
) -> tuple[PairFormationSummary, list[PairFormationEvent]]:
    by_market: dict[str, list[LedgerEntry]] = defaultdict(list)
    for row in ledger:
        if row.market_id in complete_market_ids and row.eligible_binary_market:
            by_market[row.market_id].append(row)

    sell_markets = tuple(
        sorted(mid for mid, rows in by_market.items() if any(row.side == "SELL" for row in rows))
    )
    events: list[PairFormationEvent] = []
    included_fill_count = 0
    included_market_count = 0
    for market_id, rows in by_market.items():
        if market_id in sell_markets:
            continue
        included_market_count += 1
        included_fill_count += len(rows)
        events.extend(_pair_one_market(rows, tie_break=tie_break))

    paired_shares = sum((event.paired_shares for event in events), start=ZERO)
    weighted_pair_cost = None
    weighted_edge = None
    below_one = sum((event.paired_shares for event in events if event.pair_cost < ONE), start=ZERO)
    zero_lag = sum((event.paired_shares for event in events if event.lag_seconds == 0), start=ZERO)
    if paired_shares > ZERO:
        weighted_pair_cost = (
            sum((event.pair_cost * event.paired_shares for event in events), start=ZERO)
            / paired_shares
        )
        weighted_edge = ONE - weighted_pair_cost

    summary = PairFormationSummary(
        market_count=included_market_count,
        fill_count=included_fill_count,
        pair_fragment_count=len(events),
        paired_shares=paired_shares,
        weighted_pair_cost=weighted_pair_cost,
        weighted_gross_pair_edge=weighted_edge,
        paired_shares_below_one=below_one,
        below_one_ratio=below_one / paired_shares if paired_shares > ZERO else None,
        zero_lag_paired_shares=zero_lag,
        zero_lag_ratio=zero_lag / paired_shares if paired_shares > ZERO else None,
        excluded_sell_markets=sell_markets,
    )
    return summary, events
