from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from decimal import Decimal
from statistics import median
from typing import Literal

from polymarket_edge_lab.analysis.bounded_pair_claim import btc_5m_market_start
from polymarket_edge_lab.models.reconstruction import LedgerEntry

ZERO = Decimal("0")
ONE = Decimal("1")
Method = Literal["fifo", "lifo", "weighted_average"]

LATENCY_BUCKETS = (
    "0s",
    "1s",
    "2-5s",
    "6-15s",
    "16-30s",
    "31-60s",
    "61-120s",
    ">120s",
)
TIME_BUCKETS = tuple(f"[{start},{start + 30})" for start in range(0, 300, 30))
TIME_BANDS = ("early_0_99", "middle_100_199", "late_200_299")


@dataclass(frozen=True)
class SensitivityPairEvent:
    method: str
    market_id: str
    slug: str | None
    formed_at_epoch: int
    paired_shares: Decimal
    pair_cost: Decimal
    lag_seconds: int | None
    elapsed_seconds: int | None
    transaction_hash: str | None


@dataclass(frozen=True)
class MethodSummary:
    method: str
    market_count: int
    event_count: int
    paired_shares: Decimal
    weighted_pair_cost: Decimal | None
    gross_edge: Decimal | None
    below_one_ratio: Decimal | None


def latency_bucket(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    if seconds == 1:
        return "1s"
    if seconds <= 5:
        return "2-5s"
    if seconds <= 15:
        return "6-15s"
    if seconds <= 30:
        return "16-30s"
    if seconds <= 60:
        return "31-60s"
    if seconds <= 120:
        return "61-120s"
    return ">120s"


def market_time_bucket(seconds: int) -> str | None:
    if seconds < 0 or seconds >= 300:
        return None
    start = (seconds // 30) * 30
    return f"[{start},{start + 30})"


def market_time_band(seconds: int) -> str | None:
    if 0 <= seconds <= 99:
        return "early_0_99"
    if 100 <= seconds <= 199:
        return "middle_100_199"
    if 200 <= seconds <= 299:
        return "late_200_299"
    return None


def _rows_by_market(
    ledger: list[LedgerEntry], complete_market_ids: set[str]
) -> tuple[dict[str, list[LedgerEntry]], tuple[str, ...]]:
    grouped: dict[str, list[LedgerEntry]] = defaultdict(list)
    for row in ledger:
        if row.market_id in complete_market_ids and row.eligible_binary_market:
            grouped[row.market_id].append(row)
    sell_markets = tuple(
        sorted(mid for mid, rows in grouped.items() if any(row.side == "SELL" for row in rows))
    )
    return grouped, sell_markets


def _event(
    *,
    method: Method,
    row: LedgerEntry,
    qty: Decimal,
    pair_cost: Decimal,
    lag_seconds: int | None,
) -> SensitivityPairEvent:
    start = btc_5m_market_start(row.slug)
    formed_epoch = int(row.timestamp.timestamp())
    elapsed = formed_epoch - start if start is not None else None
    return SensitivityPairEvent(
        method=method,
        market_id=row.market_id,
        slug=row.slug,
        formed_at_epoch=formed_epoch,
        paired_shares=qty,
        pair_cost=pair_cost,
        lag_seconds=lag_seconds,
        elapsed_seconds=elapsed,
        transaction_hash=row.transaction_hash,
    )


def _lot_pair_market(
    rows: list[LedgerEntry], *, method: Literal["fifo", "lifo"]
) -> list[SensitivityPairEvent]:
    lots: dict[str, deque[tuple[Decimal, Decimal, object]]] = {
        "UP": deque(),
        "DOWN": deque(),
    }
    events: list[SensitivityPairEvent] = []
    for row in sorted(rows, key=lambda r: (r.timestamp, r.fill_sequence_number)):
        side = row.normalized_outcome_side
        if side not in {"UP", "DOWN"} or row.side != "BUY":
            continue
        opposite = "DOWN" if side == "UP" else "UP"
        remaining = row.shares
        while remaining > ZERO and lots[opposite]:
            index = 0 if method == "fifo" else -1
            opp_qty, opp_price, opp_ts = lots[opposite][index]
            formed = min(remaining, opp_qty)
            lag = max(0, int((row.timestamp - opp_ts).total_seconds()))  # type: ignore[operator]
            events.append(
                _event(
                    method=method,
                    row=row,
                    qty=formed,
                    pair_cost=row.price + opp_price,
                    lag_seconds=lag,
                )
            )
            remaining -= formed
            opp_qty -= formed
            if opp_qty == ZERO:
                if method == "fifo":
                    lots[opposite].popleft()
                else:
                    lots[opposite].pop()
            else:
                lots[opposite][index] = (opp_qty, opp_price, opp_ts)
        if remaining > ZERO:
            lots[side].append((remaining, row.price, row.timestamp))
    return events


def _weighted_average_market(rows: list[LedgerEntry]) -> list[SensitivityPairEvent]:
    qty = {"UP": ZERO, "DOWN": ZERO}
    cost = {"UP": ZERO, "DOWN": ZERO}
    last_ts = {"UP": None, "DOWN": None}
    paired_before = ZERO
    events: list[SensitivityPairEvent] = []
    for row in sorted(rows, key=lambda r: (r.timestamp, r.fill_sequence_number)):
        side = row.normalized_outcome_side
        if side not in {"UP", "DOWN"} or row.side != "BUY":
            continue
        qty[side] += row.shares
        cost[side] += row.shares * row.price
        last_ts[side] = row.timestamp
        paired_after = min(qty["UP"], qty["DOWN"])
        delta = paired_after - paired_before
        if delta > ZERO and qty["UP"] > ZERO and qty["DOWN"] > ZERO:
            avg_up = cost["UP"] / qty["UP"]
            avg_down = cost["DOWN"] / qty["DOWN"]
            opposite = "DOWN" if side == "UP" else "UP"
            opposite_ts = last_ts[opposite]
            lag = None
            if opposite_ts is not None:
                lag = max(0, int((row.timestamp - opposite_ts).total_seconds()))
            events.append(
                _event(
                    method="weighted_average",
                    row=row,
                    qty=delta,
                    pair_cost=avg_up + avg_down,
                    lag_seconds=lag,
                )
            )
        paired_before = paired_after
    return events


def pair_events_by_method(
    ledger: list[LedgerEntry], *, complete_market_ids: set[str]
) -> tuple[dict[str, list[SensitivityPairEvent]], tuple[str, ...]]:
    grouped, sell_markets = _rows_by_market(ledger, complete_market_ids)
    result: dict[str, list[SensitivityPairEvent]] = {
        "fifo": [],
        "lifo": [],
        "weighted_average": [],
    }
    for market_id, rows in grouped.items():
        if market_id in sell_markets:
            continue
        result["fifo"].extend(_lot_pair_market(rows, method="fifo"))
        result["lifo"].extend(_lot_pair_market(rows, method="lifo"))
        result["weighted_average"].extend(_weighted_average_market(rows))
    return result, sell_markets


def summarize_events(method: str, events: list[SensitivityPairEvent]) -> MethodSummary:
    paired = sum((e.paired_shares for e in events), start=ZERO)
    cost = None
    edge = None
    below = None
    if paired > ZERO:
        cost = sum((e.pair_cost * e.paired_shares for e in events), start=ZERO) / paired
        edge = ONE - cost
        below_qty = sum((e.paired_shares for e in events if e.pair_cost < ONE), start=ZERO)
        below = below_qty / paired
    return MethodSummary(
        method=method,
        market_count=len({e.market_id for e in events}),
        event_count=len(events),
        paired_shares=paired,
        weighted_pair_cost=cost,
        gross_edge=edge,
        below_one_ratio=below,
    )


def _bucket_metrics(
    events: list[SensitivityPairEvent], labels: tuple[str, ...], key_fn: object
) -> list[dict[str, object]]:
    grouped: dict[str, list[SensitivityPairEvent]] = {label: [] for label in labels}
    for event in events:
        label = key_fn(event)  # type: ignore[operator]
        if label in grouped:
            grouped[label].append(event)
    total = sum((e.paired_shares for e in events), start=ZERO)
    rows: list[dict[str, object]] = []
    for label in labels:
        bucket_events = grouped[label]
        qty = sum((e.paired_shares for e in bucket_events), start=ZERO)
        pair_cost = None
        edge = None
        below = None
        if qty > ZERO:
            pair_cost = (
                sum((e.pair_cost * e.paired_shares for e in bucket_events), start=ZERO) / qty
            )
            edge = ONE - pair_cost
            below_qty = sum(
                (e.paired_shares for e in bucket_events if e.pair_cost < ONE), start=ZERO
            )
            below = below_qty / qty
        rows.append(
            {
                "bucket": label,
                "paired_shares": qty,
                "share_of_total": qty / total if total > ZERO else None,
                "weighted_pair_cost": pair_cost,
                "gross_edge": edge,
                "below_one_ratio": below,
                "event_count": len(bucket_events),
            }
        )
    return rows


def latency_metrics(events: list[SensitivityPairEvent]) -> list[dict[str, object]]:
    return _bucket_metrics(
        events,
        LATENCY_BUCKETS,
        lambda e: latency_bucket(e.lag_seconds or 0),
    )


def market_time_metrics(
    events: list[SensitivityPairEvent],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    buckets = _bucket_metrics(
        events,
        TIME_BUCKETS,
        lambda e: market_time_bucket(e.elapsed_seconds if e.elapsed_seconds is not None else -1),
    )
    bands = _bucket_metrics(
        events,
        TIME_BANDS,
        lambda e: market_time_band(e.elapsed_seconds if e.elapsed_seconds is not None else -1),
    )
    return buckets, bands


def per_market_metrics(
    events_by_method: dict[str, list[SensitivityPairEvent]],
) -> list[dict[str, object]]:
    market_ids = sorted({e.market_id for events in events_by_method.values() for e in events})
    rows: list[dict[str, object]] = []
    for market_id in market_ids:
        row: dict[str, object] = {"market_id": market_id}
        sample = next(
            e for events in events_by_method.values() for e in events if e.market_id == market_id
        )
        row["slug"] = sample.slug
        start = btc_5m_market_start(sample.slug)
        row["market_start_epoch"] = start
        row["market_end_epoch"] = start + 300 if start is not None else None
        for method, events in events_by_method.items():
            subset = [e for e in events if e.market_id == market_id]
            summary = summarize_events(method, subset)
            row[method] = asdict(summary)
        rows.append(row)
    return rows


def distribution(values: list[Decimal]) -> dict[str, Decimal | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    ordered = sorted(values)

    def percentile(p: Decimal) -> Decimal:
        index = int((Decimal(len(ordered) - 1) * p).to_integral_value(rounding="ROUND_HALF_UP"))
        return ordered[index]

    return {
        "count": len(values),
        "mean": sum(values, start=ZERO) / Decimal(len(values)),
        "median": Decimal(str(median(values))),
        "p10": percentile(Decimal("0.10")),
        "p25": percentile(Decimal("0.25")),
        "p75": percentile(Decimal("0.75")),
        "p90": percentile(Decimal("0.90")),
        "min": ordered[0],
        "max": ordered[-1],
    }


def transaction_hash_diagnostic(
    ledger: list[LedgerEntry], complete_market_ids: set[str]
) -> dict[str, object]:
    grouped, sell_markets = _rows_by_market(ledger, complete_market_ids)
    hashes: dict[str, list[LedgerEntry]] = defaultdict(list)
    for market_id, rows in grouped.items():
        if market_id in sell_markets:
            continue
        for row in rows:
            if row.side == "BUY" and row.transaction_hash:
                hashes[row.transaction_hash].append(row)
    fill_counts = [Decimal(len(rows)) for rows in hashes.values()]
    same_hash_events: list[SensitivityPairEvent] = []
    paired_hashes = 0
    for rows in hashes.values():
        markets = defaultdict(list)
        for row in rows:
            markets[row.market_id].append(row)
        hash_paired = False
        for market_rows in markets.values():
            events = _lot_pair_market(market_rows, method="fifo")
            if events:
                hash_paired = True
                same_hash_events.extend(events)
        if hash_paired:
            paired_hashes += 1
    summary = summarize_events("same_transaction_hash_fifo", same_hash_events)
    return {
        "distinct_transaction_hashes": len(hashes),
        "fills_per_hash_distribution": distribution(fill_counts),
        "hashes_with_complementary_pairing": paired_hashes,
        "same_hash_pair_summary": asdict(summary),
    }
