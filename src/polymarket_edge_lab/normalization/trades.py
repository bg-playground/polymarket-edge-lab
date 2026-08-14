"""Trade normalization: converts raw API dicts into NormalizedTrade objects.

Field mappings are derived from the official Polymarket Data API documentation
(https://docs.polymarket.com/) and the documented response shape of
GET https://data-api.polymarket.com/trades.

Schema status (2026-08-14): field names verified against official Polymarket
Data API documentation.  Live response shape not confirmed due to network
restriction during implementation — see tests/fixtures/README.md.
TODO: Confirm field names and types against a live response before production use.

Public Data API field mapping
-----------------------------
``conditionId``  → ``market_id``   (hex condition/market ID)
``asset``        → ``asset_id``    (CTF token ID; required for UP/DOWN analysis)
``proxyWallet``  → ``account``
``timestamp``    → ``timestamp``   (Unix milliseconds integer → UTC datetime)
                               NOTE: unit assumed milliseconds from fixture evidence;
                               live response not confirmed — see TODO below.
``transactionHash`` → ``transaction_hash``
``side``, ``size``, ``price``, ``outcome`` retained as-is.

NOTE: The Data API does not appear to guarantee a unique fill ID per row.
``id`` is used when present; otherwise a deterministic SHA-256 hash of the
key tuple is used as ``source_trade_id``.  Economically identical fills in
the same transaction may therefore be indistinguishable.
TODO: Confirm uniqueness guarantee of ``id`` against live responses.
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
# These match the public Polymarket Data API /trades response shape.
REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"conditionId", "asset", "side", "size", "price", "timestamp", "outcome", "proxyWallet"}
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
    from the raw record (Data API field names); missing values are represented
    as empty strings.
    """
    key_data = {
        "transactionHash": record.get("transactionHash") or "",
        "asset": record.get("asset") or "",
        "side": record.get("side") or "",
        "price": str(record.get("price") or ""),
        "size": str(record.get("size") or ""),
        "timestamp": str(record.get("timestamp") or ""),
        "proxyWallet": record.get("proxyWallet") or "",
    }
    canonical = json.dumps(key_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _parse_ms_to_utc(raw_ts: Any, field: str = "timestamp") -> datetime:
    """Parse a Unix-milliseconds value (integer) to UTC datetime.

    The public Data API documentation is inconsistent: time-filter *parameters*
    (``start``/``end``) are described in epoch **seconds**, but the response
    ``timestamp`` field appears as a large integer consistent with epoch
    **milliseconds** (values ~1.7 × 10¹²).  This function assumes
    milliseconds and raises ``ValueError`` if the parsed result falls outside
    the plausible Polymarket trading epoch (2019-10-01 → 2040-01-01) —
    catching the common mistake of passing an epoch-seconds value that would
    silently produce a 1970-era datetime.

    Schema status: unit confirmed against published fixture values
    (1 723 634 400 000 ms = 2024-08-14 11:20:00 UTC).  The unit must be
    re-verified against a live response before production use.
    TODO: Confirm milliseconds vs. seconds with a live /trades response.

    Float values are rejected to avoid silent precision loss.

    Raises ValueError for non-integer, unparseable, or out-of-plausible-range
    inputs.
    """
    if isinstance(raw_ts, float):
        raise ValueError(
            f"{field}: raw float values are rejected to avoid precision loss; "
            f"got {raw_ts!r}. Pass as integer milliseconds."
        )
    if isinstance(raw_ts, int):
        ms = raw_ts
    else:
        # String path — parse as integer.
        s = str(raw_ts).strip()
        try:
            ms = int(s)
        except ValueError as exc:
            raise ValueError(f"{field}: cannot parse as integer milliseconds: {raw_ts!r}") from exc

    result = datetime.fromtimestamp(ms / 1000, tz=UTC)
    _check_timestamp_plausibility(result, raw_ts, field)
    return result


# Plausible Polymarket trade timestamp bounds.
# Lower: 2019-10-01 (platform launch).  Upper: 2040-01-01 (far-future guard).
_TS_MIN = datetime(2019, 10, 1, tzinfo=UTC)
_TS_MAX = datetime(2040, 1, 1, tzinfo=UTC)


def _check_timestamp_plausibility(dt: datetime, raw_value: Any, field: str) -> None:
    """Log a data-quality warning if *dt* is outside the plausible trading epoch.

    An out-of-range result almost always means the raw value was in epoch
    **seconds** rather than milliseconds (which produces a 1970-era datetime),
    or the value is otherwise corrupt.  We raise ValueError so the record is
    rejected and logged rather than silently stored with a wrong timestamp.
    """
    if dt < _TS_MIN or dt > _TS_MAX:
        raise ValueError(
            f"{field}: parsed timestamp {dt.isoformat()} is outside the plausible "
            f"Polymarket trading epoch [{_TS_MIN.date()}, {_TS_MAX.date()}]. "
            f"Raw value was {raw_value!r}. "
            "Possible unit mismatch: verify whether the API returns seconds or milliseconds."
        )


def _parse_decimal(value: Any, field: str) -> Decimal:
    """Parse a price/size value from the raw API to Decimal.

    The public Data API returns ``price`` and ``size`` as JSON numbers.  When
    the response is parsed with ``json.loads(..., parse_float=Decimal)`` the
    values arrive as ``Decimal`` objects; those are returned directly.
    Plain strings and integers are also accepted.  Raw Python ``float``
    objects are rejected to avoid silent precision loss — they indicate the
    response was decoded without ``parse_float=Decimal``.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise ValueError(
            f"{field}: raw float rejected to avoid precision loss; got {value!r}. "
            "Ensure JSON is parsed with parse_float=Decimal."
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

    timestamp = _parse_ms_to_utc(record["timestamp"])

    # Verify UTC.
    utc_offset = timestamp.utcoffset()
    from datetime import timedelta

    if utc_offset is None or utc_offset != timedelta(0):
        raise ValueError(f"timestamp is not UTC: {timestamp!r}")

    # Build source trade ID: prefer API-provided id, fall back to hash.
    source_trade_id: str = str(record["id"]) if record.get("id") else _make_identity_hash(record)

    # Collect unknown fields into raw_extra.
    known_fields = {
        "id",
        "conditionId",
        "asset",
        "side",
        "size",
        "price",
        "timestamp",
        "outcome",
        "proxyWallet",
        "transactionHash",
        "outcomeIndex",
        "slug",
        "eventSlug",
        "title",
        # Less common fields that may appear:
        "takerOrderId",
        "feeRateBps",
        "status",
        "lastUpdate",
        "bucketIndex",
        "makerAddress",
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
        market_id=str(record["conditionId"]),
        asset_id=str(record["asset"]),
        timestamp=timestamp,
        outcome=str(record["outcome"]),
        side=side,
        price=price,
        shares=shares,
        transaction_hash=record.get("transactionHash") or None,
        outcome_index=record.get("outcomeIndex"),
        slug=record.get("slug") or None,
        event_slug=record.get("eventSlug") or None,
        title=record.get("title") or None,
        raw_extra=raw_extra,
    )
