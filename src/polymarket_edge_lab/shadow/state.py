from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from polymarket_edge_lab.shadow.events import NormalizedFill, OutcomeSide

ZERO = Decimal("0")


@dataclass
class _Lot:
    shares: Decimal
    price: Decimal
    source_trade_id: str


@dataclass(frozen=True)
class PairFormation:
    market_id: str
    completing_source_trade_id: str
    paired_shares: Decimal
    pair_cost: Decimal


@dataclass(frozen=True)
class QuarantineRecord:
    market_id: str
    source_trade_id: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class MarketStateSnapshot:
    market_id: str
    up_inventory: Decimal
    down_inventory: Decimal
    paired_inventory: Decimal
    residual_inventory: Decimal
    inventory_imbalance: Decimal
    cumulative_paired_quantity: Decimal
    applied_fill_count: int
    last_source_trade_id: str | None
    quarantined: bool
    quarantine_reason: str | None


class MarketStateQuarantinedError(ValueError):
    def __init__(self, record: QuarantineRecord) -> None:
        super().__init__(record.detail)
        self.record = record


class MarketOnlineState:
    """Arrival-time state with deterministic FIFO pairing and conservative sell handling."""

    def __init__(self, market_id: str) -> None:
        self.market_id = market_id
        self._up_inventory = ZERO
        self._down_inventory = ZERO
        self._up_unpaired: deque[_Lot] = deque()
        self._down_unpaired: deque[_Lot] = deque()
        self._seen_ids: set[str] = set()
        self._cumulative_paired = ZERO
        self._applied_fill_count = 0
        self._last_source_trade_id: str | None = None
        self._quarantine: QuarantineRecord | None = None

    def apply(self, fill: NormalizedFill) -> list[PairFormation]:
        if fill.market_id != self.market_id:
            raise ValueError(f"fill market {fill.market_id} does not match state {self.market_id}")
        if fill.source_trade_id in self._seen_ids:
            return []
        if self._quarantine is not None:
            raise MarketStateQuarantinedError(self._quarantine)
        if fill.shares <= ZERO:
            raise ValueError("fill shares must be positive")

        if fill.side == "SELL":
            self._validate_sell(fill)

        self._seen_ids.add(fill.source_trade_id)
        self._applied_fill_count += 1
        self._last_source_trade_id = fill.source_trade_id

        if fill.outcome_side == "UP":
            self._apply_inventory("UP", fill)
        else:
            self._apply_inventory("DOWN", fill)

        return self._form_pairs(fill.source_trade_id)

    def _validate_sell(self, fill: NormalizedFill) -> None:
        if fill.outcome_side == "UP":
            inventory = self._up_inventory
            lots = self._up_unpaired
        else:
            inventory = self._down_inventory
            lots = self._down_unpaired
        unpaired = sum((lot.shares for lot in lots), ZERO)
        if fill.shares > inventory:
            self._quarantine_and_raise(
                fill,
                "sell_exceeds_observed_inventory",
                f"sell exceeds observed {fill.outcome_side} inventory by {fill.shares - inventory}",
            )
        if fill.shares > unpaired:
            self._quarantine_and_raise(
                fill,
                "sell_would_unwind_paired_inventory",
                "sell cannot be satisfied entirely from observable unpaired FIFO residual",
            )

    def _quarantine_and_raise(self, fill: NormalizedFill, reason: str, detail: str) -> None:
        record = QuarantineRecord(
            market_id=self.market_id,
            source_trade_id=fill.source_trade_id,
            reason_code=reason,
            detail=detail,
        )
        self._quarantine = record
        raise MarketStateQuarantinedError(record)

    def _apply_inventory(self, side: OutcomeSide, fill: NormalizedFill) -> None:
        if side == "UP":
            inventory = self._up_inventory
            lots = self._up_unpaired
        else:
            inventory = self._down_inventory
            lots = self._down_unpaired

        if fill.side == "BUY":
            inventory += fill.shares
            lots.append(_Lot(fill.shares, fill.price, fill.source_trade_id))
        else:
            inventory -= fill.shares
            self._consume_lots(lots, fill.shares)

        if side == "UP":
            self._up_inventory = inventory
        else:
            self._down_inventory = inventory

    @staticmethod
    def _consume_lots(lots: deque[_Lot], shares: Decimal) -> None:
        remaining = shares
        while remaining > ZERO:
            if not lots:
                raise ValueError("FIFO lot inventory exhausted")
            lot = lots[0]
            take = min(remaining, lot.shares)
            lot.shares -= take
            remaining -= take
            if lot.shares == ZERO:
                lots.popleft()

    def _form_pairs(self, completing_source_trade_id: str) -> list[PairFormation]:
        formations: list[PairFormation] = []
        while self._up_unpaired and self._down_unpaired:
            up = self._up_unpaired[0]
            down = self._down_unpaired[0]
            paired = min(up.shares, down.shares)
            formations.append(
                PairFormation(
                    market_id=self.market_id,
                    completing_source_trade_id=completing_source_trade_id,
                    paired_shares=paired,
                    pair_cost=up.price + down.price,
                )
            )
            self._cumulative_paired += paired
            up.shares -= paired
            down.shares -= paired
            if up.shares == ZERO:
                self._up_unpaired.popleft()
            if down.shares == ZERO:
                self._down_unpaired.popleft()
        return formations

    def snapshot(self) -> MarketStateSnapshot:
        paired = min(self._up_inventory, self._down_inventory)
        residual = abs(self._up_inventory - self._down_inventory)
        total = self._up_inventory + self._down_inventory
        imbalance = ZERO if total == ZERO else (self._up_inventory - self._down_inventory) / total
        return MarketStateSnapshot(
            market_id=self.market_id,
            up_inventory=self._up_inventory,
            down_inventory=self._down_inventory,
            paired_inventory=paired,
            residual_inventory=residual,
            inventory_imbalance=imbalance,
            cumulative_paired_quantity=self._cumulative_paired,
            applied_fill_count=self._applied_fill_count,
            last_source_trade_id=self._last_source_trade_id,
            quarantined=self._quarantine is not None,
            quarantine_reason=None if self._quarantine is None else self._quarantine.reason_code,
        )
