"""Normalized trade models used by the forensic pipeline."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NormalizedTrade(BaseModel):
    """Canonical representation of one observed public trade fill.

    Fields are mapped from the public Polymarket Data API
    (``https://data-api.polymarket.com/trades``) response shape.

    Forensic provenance fields
    --------------------------
    ``asset_id``
        CTF token ID (``asset`` field from Data API).  Required for
        token-level UP/DOWN reconstruction in later milestones.
    ``market_id``
        Condition/market ID (``conditionId`` field).
    ``outcome_index``
        Numeric outcome index when present (``outcomeIndex``).
    ``slug``
        Market slug for human-readable identification (``slug``).
    ``event_slug``
        Event slug (``eventSlug``).
    ``title``
        Market question/title (``title``).
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    source: str
    source_trade_id: str
    account: str
    market_id: str
    asset_id: str
    timestamp: datetime
    outcome: str
    side: Literal["BUY", "SELL"]
    price: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    shares: Decimal = Field(gt=Decimal("0"))
    transaction_hash: str | None = None
    outcome_index: int | None = None
    slug: str | None = None
    event_slug: str | None = None
    title: str | None = None
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
