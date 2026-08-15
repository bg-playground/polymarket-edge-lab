from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from polymarket_edge_lab.analysis.bounded_pair_claim import btc_5m_market_start
from polymarket_edge_lab.analysis.btc_features import BtcCandle, build_btc_features
from polymarket_edge_lab.models.reconstruction import LedgerEntry

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class _Lot:
    shares: Decimal
    price: Decimal
    timestamp: datetime


@dataclass(frozen=True)
class _PriorFill:
    epoch: int
    sequence: int
    side: str
    shares: Decimal


def _numeric(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def _seconds_since(now: datetime, then: datetime | None) -> int | None:
    if then is None:
        return None
    return max(0, int((now - then).total_seconds()))


def _trailing(fills: deque[_PriorFill], now_epoch: int, seconds: int) -> tuple[int, Decimal]:
    cutoff = now_epoch - seconds
    selected = [fill for fill in fills if fill.epoch >= cutoff]
    return len(selected), sum((fill.shares for fill in selected), start=ZERO)


def _switches(fills: deque[_PriorFill], now_epoch: int, seconds: int) -> int:
    cutoff = now_epoch - seconds
    sides = [fill.side for fill in fills if fill.epoch >= cutoff]
    return sum(1 for left, right in zip(sides, sides[1:], strict=False) if left != right)


def _snapshot(
    *,
    row: LedgerEntry,
    qty: dict[str, Decimal],
    last_ts: dict[str, datetime | None],
    recent: deque[_PriorFill],
    cumulative_paired: Decimal,
) -> dict[str, Any]:
    epoch = int(row.timestamp.timestamp())
    paired = min(qty["UP"], qty["DOWN"])
    residual = abs(qty["UP"] - qty["DOWN"])
    total = qty["UP"] + qty["DOWN"]
    imbalance = (qty["UP"] - qty["DOWN"]) / total if total > ZERO else None
    count15, qty15 = _trailing(recent, epoch, 15)
    count30, qty30 = _trailing(recent, epoch, 30)
    count60, qty60 = _trailing(recent, epoch, 60)
    start = btc_5m_market_start(row.slug)
    elapsed = epoch - start if start is not None else None
    return {
        "prediction_time_epoch": epoch,
        "prediction_fill_sequence": row.fill_sequence_number,
        "elapsed_seconds": elapsed,
        "seconds_remaining": 300 - elapsed if elapsed is not None else None,
        "up_inventory": qty["UP"],
        "down_inventory": qty["DOWN"],
        "paired_inventory": paired,
        "residual_inventory": residual,
        "inventory_imbalance": imbalance,
        "seconds_since_last_up_fill": _seconds_since(row.timestamp, last_ts["UP"]),
        "seconds_since_last_down_fill": _seconds_since(row.timestamp, last_ts["DOWN"]),
        "fill_count_15s": count15,
        "fill_count_30s": count30,
        "fill_count_60s": count60,
        "fill_qty_15s": qty15,
        "fill_qty_30s": qty30,
        "fill_qty_60s": qty60,
        "side_switches_60s": _switches(recent, epoch, 60),
        "cumulative_paired_quantity": cumulative_paired,
        "same_second_fill_count": sum(1 for fill in recent if fill.epoch == epoch),
        "max_prior_fill_sequence": max((fill.sequence for fill in recent), default=None),
    }


def build_pre_event_rows(
    ledger: list[LedgerEntry],
    *,
    complete_market_ids: set[str],
    btc_candles: list[BtcCandle],
    window_id: str,
) -> list[dict[str, Any]]:
    """Rebuild FIFO labels while snapshotting state before each completing fill."""
    grouped: dict[str, list[LedgerEntry]] = defaultdict(list)
    for row in ledger:
        if (
            row.market_id in complete_market_ids
            and row.eligible_binary_market
            and row.side == "BUY"
            and row.normalized_outcome_side in {"UP", "DOWN"}
        ):
            grouped[row.market_id].append(row)

    result: list[dict[str, Any]] = []
    for market_id, market_rows in grouped.items():
        lots: dict[str, deque[_Lot]] = {"UP": deque(), "DOWN": deque()}
        qty = {"UP": ZERO, "DOWN": ZERO}
        last_ts: dict[str, datetime | None] = {"UP": None, "DOWN": None}
        recent: deque[_PriorFill] = deque()
        cumulative_paired = ZERO

        ordered_rows = sorted(
            market_rows,
            key=lambda item: (item.timestamp, item.fill_sequence_number),
        )
        for row in ordered_rows:
            side = row.normalized_outcome_side
            if side not in {"UP", "DOWN"}:
                continue
            epoch = int(row.timestamp.timestamp())
            while recent and recent[0].epoch < epoch - 120:
                recent.popleft()

            pre = _snapshot(
                row=row,
                qty=qty,
                last_ts=last_ts,
                recent=recent,
                cumulative_paired=cumulative_paired,
            )
            opposite = "DOWN" if side == "UP" else "UP"
            remaining = row.shares
            event_index = 0
            while remaining > ZERO and lots[opposite]:
                lot = lots[opposite][0]
                formed = min(remaining, lot.shares)
                lag = max(0, int((row.timestamp - lot.timestamp).total_seconds()))
                pair_cost = row.price + lot.price
                btc = build_btc_features(
                    btc_candles,
                    event_epoch=epoch,
                    market_start_epoch=btc_5m_market_start(row.slug),
                )
                output = {
                    "window_id": window_id,
                    "market_id": market_id,
                    "slug": row.slug,
                    "target_source_trade_id": row.source_trade_id,
                    "target_transaction_hash": row.transaction_hash,
                    "target_event_index": event_index,
                    "paired_shares": formed,
                    "pair_cost": pair_cost,
                    "favorable": pair_cost < ONE,
                    "lag_seconds_label_only": lag,
                    **pre,
                }
                for key, value in asdict(btc).items():
                    if key != "event_epoch":
                        output[f"btc_{key}"] = value
                result.append({key: _numeric(value) for key, value in output.items()})
                cumulative_paired += formed
                remaining -= formed
                leftover = lot.shares - formed
                if leftover == ZERO:
                    lots[opposite].popleft()
                else:
                    lots[opposite][0] = _Lot(leftover, lot.price, lot.timestamp)
                event_index += 1

            if remaining > ZERO:
                lots[side].append(_Lot(remaining, row.price, row.timestamp))
            qty[side] += row.shares
            last_ts[side] = row.timestamp
            recent.append(
                _PriorFill(
                    epoch=epoch,
                    sequence=row.fill_sequence_number,
                    side=side,
                    shares=row.shares,
                )
            )

    return sorted(
        result,
        key=lambda item: (
            int(item["prediction_time_epoch"]),
            str(item["market_id"]),
            int(item["prediction_fill_sequence"]),
            int(item["target_event_index"]),
        ),
    )


def audit_pre_event_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[str] = []
    for index, row in enumerate(rows):
        prior_sequence = row.get("max_prior_fill_sequence")
        target_sequence = row.get("prediction_fill_sequence")
        if prior_sequence is not None and target_sequence is not None:
            if int(prior_sequence) >= int(target_sequence):
                violations.append(f"row {index}: prior sequence is not strictly before target")
        btc_epoch = row.get("btc_reference_epoch")
        prediction_epoch = row.get("prediction_time_epoch")
        if btc_epoch is not None and prediction_epoch is not None:
            if int(btc_epoch) > int(prediction_epoch):
                violations.append(f"row {index}: BTC reference is later than prediction time")
    return {
        "row_count": len(rows),
        "violation_count": len(violations),
        "passed": not violations,
        "violations": violations[:100],
    }
