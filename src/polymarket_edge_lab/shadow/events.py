from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

EventType = Literal[
    "raw_observation",
    "normalized_fill",
    "btc_candle",
    "market_metadata",
    "score_attempt",
    "prediction",
    "unscorable_tick",
    "outcome_label",
    "score_binding",
    "source_health",
    "state_reconciliation",
    "replay_audit",
]

OutcomeSide = Literal["UP", "DOWN"]
TradeSide = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class EventEnvelope:
    schema_version: str
    event_type: EventType
    event_id: str
    run_id: str
    sequence: int
    created_at: datetime
    payload: dict[str, object]
    supersedes_event_id: str | None = None

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["created_at"] = self.created_at.astimezone(UTC).isoformat()
        return record


@dataclass(frozen=True)
class NormalizedFill:
    source_trade_id: str
    market_id: str
    asset_id: str
    outcome_side: OutcomeSide
    side: TradeSide
    source_timestamp: datetime
    price: Decimal
    shares: Decimal
    receive_timestamp: datetime
    local_ingest_id: str

    def to_payload(self) -> dict[str, object]:
        return {
            "source_trade_id": self.source_trade_id,
            "market_id": self.market_id,
            "asset_id": self.asset_id,
            "outcome_side": self.outcome_side,
            "side": self.side,
            "source_timestamp": self.source_timestamp.astimezone(UTC).isoformat(),
            "price": str(self.price),
            "shares": str(self.shares),
            "receive_timestamp": self.receive_timestamp.astimezone(UTC).isoformat(),
            "local_ingest_id": self.local_ingest_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> NormalizedFill:
        return cls(
            source_trade_id=str(payload["source_trade_id"]),
            market_id=str(payload["market_id"]),
            asset_id=str(payload["asset_id"]),
            outcome_side=_outcome_side(payload["outcome_side"]),
            side=_trade_side(payload["side"]),
            source_timestamp=datetime.fromisoformat(str(payload["source_timestamp"])),
            price=Decimal(str(payload["price"])),
            shares=Decimal(str(payload["shares"])),
            receive_timestamp=datetime.fromisoformat(str(payload["receive_timestamp"])),
            local_ingest_id=str(payload["local_ingest_id"]),
        )


def _outcome_side(value: object) -> OutcomeSide:
    text = str(value)
    if text not in {"UP", "DOWN"}:
        raise ValueError(f"invalid outcome side: {text}")
    return text  # type: ignore[return-value]


def _trade_side(value: object) -> TradeSide:
    text = str(value)
    if text not in {"BUY", "SELL"}:
        raise ValueError(f"invalid trade side: {text}")
    return text  # type: ignore[return-value]
