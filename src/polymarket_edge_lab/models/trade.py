"""Normalized trade models used by the forensic pipeline."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NormalizedTrade(BaseModel):
    """Canonical representation of one observed public trade fill."""

    model_config = ConfigDict(extra="allow", frozen=True)

    source: str
    source_trade_id: str
    account: str
    market_id: str
    timestamp: datetime
    outcome: str
    side: Literal["BUY", "SELL"]
    price: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    shares: Decimal = Field(gt=Decimal("0"))
    transaction_hash: str | None = None
    raw_extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @property
    def notional(self) -> Decimal:
        return self.price * self.shares
