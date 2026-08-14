"""Trade normalization: converts raw API dicts into NormalizedTrade objects.

Field mappings are derived from the official Polymarket Data API documentation
(https://docs.polymarket.com/) and the documented response shape of
GET https://data-api.polymarket.com/trades.

Verified endpoint shape (2026-08-14): JSON array of objects with at minimum
the keys listed in REQUIRED_FIELDS. Response confirmed to return Unix-seconds
timestamps as string-encoded integers in the ``match_time`` field.

NOTE: The Data API does not appear to guarantee a unique fill ID per row.
``id`` is used when present; otherwise a deterministic SHA-256 hash of
(transaction_hash, asset_id, side, price, size, match_time, owner) is used
as ``source_trade_id``.  Economically identical fills in the same transaction
may therefore be indistinguishable if the API omits a fill ID.
TODO: Confirm uniqueness guarantee of ``id`` against additional live responses.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from polymarket_edge_lab.models.trade import NormalizedTrade

logger = logging.getLogger(__name__)

# Fields that must be present and non-empty for a record to be accepted.
REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"market", "asset_id", "side", "size", "price", "match_time", "outcome", "owner"}
)

SOURCE_NAME = "polymarket-data-api"


@dataclass(frozen=True)
class RejectedRecord:
    index: int
    reason: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class NormalizationResult:
    accepted: list[NormalizedTrade]
    rejected: list[RejectedRecord]
    duplicate_ids: list[str]

    @property
    def total_input(self) -> int:
        return len(self.accepted) + len(self.rejected) + len(self.duplicate_ids)


def _make_identity_hash(record: dict[str, Any]) -> str:
    """Build a deterministic deduplication key from verified source fields.

    Uses SHA-256 of the canonical JSON-serialized key tuple. Fields are taken
    from the raw record; missing values are represented as empty strings.
    """
    key_data = {
        "transaction_hash": record.get("transaction_hash") or "",
        "asset_id": record.get("asset_id") or "",
        "side": record.get("side") or "",
        "price": record.get("price") or "",
        "size": record.get("size") or "",
        "match_time": record.get("match_time") or "",
        "owner": record.get("owner") or "",
    }
    canonical = json.dumps(key_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _parse_unix_seconds_to_utc(raw_ts: Any, field: str = "match_time") -> datetime:
    """Parse a Unix-seconds value (int, float string, or numeric string) to UTC.

    Raises ValueError if the value is not a clean integral seconds value.
    Float strings with a decimal part (e.g. "1723634400.5") are rejected as
    ambiguous unless the fractional part is exactly zero.
    """
    if isinstance(raw_ts, float):
        # Reject raw Python floats — they may lose precision.
        raise ValueError(
            f"{field}: raw float values are rejected to avoid precision loss; "
            f"got {raw_ts!r}. Pass as int or numeric string."
        )
    if isinstance(raw_ts, int):
        return datetime.fromtimestamp(raw_ts, tz=UTC)
    # String path — common for this API.
    s = str(raw_ts).strip()
    if "." in s:
        int_part, frac_part = s.split(".", 1)
        if frac_part.lstrip("0"):
            raise ValueError(f"{field}: sub-second timestamp {raw_ts!r} is ambiguous/unsupported")
        s = int_part
    try:
        seconds = int(s)
    except ValueError as exc:
        raise ValueError(f"{field}: cannot parse as integer seconds: {raw_ts!r}") from exc
    return datetime.fromtimestamp(seconds, tz=UTC)


def _parse_decimal(value: Any, field: str) -> Decimal:
    """Parse a price/size value from the raw API string to Decimal.

    Avoids float intermediates to preserve precision.
    """
    if isinstance(value, float):
        raise ValueError(
            f"{field}: raw float rejected to avoid precision loss; got {value!r}. "
            "Ensure JSON is parsed with parse_float=Decimal or string values are used."
        )
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field}: cannot parse as Decimal: {value!r}") from exc


def normalize_records(
    raw_records: list[dict[str, Any]],
    *,
    account: str,
    raw_page_path: str = "",
    raw_page_hash: str = "",
    offset: int = 0,
) -> NormalizationResult:
    """Normalize a list of raw API dicts into NormalizedTrade objects.

    Parameters
    ----------
    raw_records:
        The parsed JSON array from one API page.
    account:
        The proxy-wallet address being collected (used as NormalizedTrade.account).
    raw_page_path:
        Path to the stored raw file (stored in raw_extra for provenance).
    raw_page_hash:
        SHA-256 hex digest of the raw file (stored in raw_extra for provenance).
    offset:
        API offset of this page (stored in raw_extra for provenance).
    """
    accepted: list[NormalizedTrade] = []
    rejected: list[RejectedRecord] = []
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []

    for idx, record in enumerate(raw_records):
        try:
            _check_required_fields(idx, record)
            trade = _normalize_one(
                idx,
                record,
                account=account,
                raw_page_path=raw_page_path,
                raw_page_hash=raw_page_hash,
                offset=offset,
            )
        except ValueError as exc:
            logger.warning("Record %d rejected: %s", idx, exc)
            rejected.append(RejectedRecord(index=idx, reason=str(exc), raw=record))
            continue

        if trade.source_trade_id in seen_ids:
            logger.warning("Duplicate trade id at record %d: %s", idx, trade.source_trade_id)
            duplicate_ids.append(trade.source_trade_id)
            continue

        seen_ids.add(trade.source_trade_id)
        accepted.append(trade)

    return NormalizationResult(accepted=accepted, rejected=rejected, duplicate_ids=duplicate_ids)


def _check_required_fields(idx: int, record: dict[str, Any]) -> None:
    missing = [f for f in REQUIRED_FIELDS if not record.get(f)]
    if missing:
        raise ValueError(f"Record {idx} missing required fields: {sorted(missing)}")


def _normalize_one(
    idx: int,
    record: dict[str, Any],
    *,
    account: str,
    raw_page_path: str,
    raw_page_hash: str,
    offset: int,
) -> NormalizedTrade:
    side = record["side"]
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Unsupported side value: {side!r}; expected 'BUY' or 'SELL'")

    price = _parse_decimal(record["price"], "price")
    if price < Decimal("0") or price > Decimal("1"):
        raise ValueError(f"price out of range [0, 1]: {price}")

    shares = _parse_decimal(record["size"], "size")
    if shares <= Decimal("0"):
        raise ValueError(f"size must be > 0: {shares}")

    timestamp = _parse_unix_seconds_to_utc(record["match_time"])

    # Normalise to UTC (verify offset is zero).
    utc_offset = timestamp.utcoffset()
    from datetime import timedelta

    if utc_offset is None or utc_offset != timedelta(0):
        raise ValueError(f"timestamp is not UTC: {timestamp!r}")

    # Build source trade ID: prefer API-provided id, fall back to hash.
    source_trade_id: str = str(record["id"]) if record.get("id") else _make_identity_hash(record)

    # Collect unknown fields into raw_extra.
    known_fields = {
        "id",
        "market",
        "asset_id",
        "side",
        "size",
        "price",
        "match_time",
        "outcome",
        "owner",
        "transaction_hash",
        "taker_order_id",
        "fee_rate_bps",
        "status",
        "last_update",
        "bucket_index",
        "maker_address",
    }
    raw_extra = {k: v for k, v in record.items() if k not in known_fields}
    raw_extra["_raw_page_path"] = raw_page_path
    raw_extra["_raw_page_hash"] = raw_page_hash
    raw_extra["_page_offset"] = offset
    raw_extra["_record_index"] = idx

    return NormalizedTrade(
        source=SOURCE_NAME,
        source_trade_id=source_trade_id,
        account=account,
        market_id=str(record["market"]),
        timestamp=timestamp,
        outcome=str(record["outcome"]),
        side=side,
        price=price,
        shares=shares,
        transaction_hash=record.get("transaction_hash") or None,
        raw_extra=raw_extra,
    )
