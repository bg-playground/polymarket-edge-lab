from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from polymarket_edge_lab.analysis.btc_features import BtcFeatureRow, build_btc_features
from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.shadow.btc_collector import load_latest_btc_candles
from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.market_metadata import EligibleMarketMetadata
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

FEATURE_SCHEMA_VERSION = "m4a-stage3g-feature-v1"
PRIMARY_MODEL_NAME = "hgb_all_pre_event"
PRIMARY_FEATURES = MODEL_FEATURES[PRIMARY_MODEL_NAME]
TARGET_HEALTH_MAX_AGE_SECONDS = 5
BTC_MAX_AGE_SECONDS = 120
EVALUATION_START_HOUR_UTC = 12
EVALUATION_END_HOUR_UTC = 18
DEFAULT_TICK_INTERVAL_SECONDS = 1.0
ZERO = Decimal("0")

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class FeatureTickResult:
    market_id: str
    scorable: bool
    event_id: str
    reason_code: str | None


@dataclass(frozen=True)
class _AppliedFill:
    application_sequence: int
    fill_event_id: str
    fill: NormalizedFill


@dataclass(frozen=True)
class _FeatureState:
    up_inventory: Decimal
    down_inventory: Decimal
    paired_inventory: Decimal
    residual_inventory: Decimal
    inventory_imbalance: Decimal | None
    seconds_since_last_up_fill: int | None
    seconds_since_last_down_fill: int | None
    fill_count_15s: int
    fill_count_30s: int
    fill_count_60s: int
    fill_qty_15s: Decimal
    fill_qty_30s: Decimal
    fill_qty_60s: Decimal
    side_switches_60s: int
    cumulative_paired_quantity: Decimal
    same_second_fill_count: int
    max_source_timestamp: datetime | None
    max_fill_key: tuple[datetime, str, str] | None
    max_receive_timestamp: datetime | None


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _record_created_at(record: dict[str, object]) -> datetime:
    return datetime.fromisoformat(str(record["created_at"]))


def _numeric(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _seconds_since(event_epoch: int, timestamp: datetime | None) -> int | None:
    if timestamp is None:
        return None
    return max(0, event_epoch - int(timestamp.timestamp()))


def _market_metadata(
    records: list[dict[str, object]], market_id: str
) -> EligibleMarketMetadata | None:
    latest: EligibleMarketMetadata | None = None
    for record in records:
        if record.get("event_type") != "market_metadata":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if str(payload.get("condition_id") or "").lower() != market_id.lower():
            continue
        if payload.get("eligible") is not True:
            latest = None
            continue
        metadata_payload = payload.get("metadata")
        if isinstance(metadata_payload, dict):
            latest = EligibleMarketMetadata.from_payload(metadata_payload)
    return latest


def _latest_target_poll_ok(records: list[dict[str, object]]) -> datetime | None:
    latest: datetime | None = None
    for record in records:
        if record.get("event_type") != "source_health":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("source") != "polymarket-data-api" or payload.get("status") != "poll_ok":
            continue
        latest = _record_created_at(record)
    return latest


def _market_quarantined(records: list[dict[str, object]], market_id: str) -> bool:
    for record in records:
        event_type = record.get("event_type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if str(payload.get("market_id") or "").lower() != market_id.lower():
            continue
        if event_type == "state_quarantine":
            return True
        if event_type == "state_application":
            snapshot = payload.get("snapshot")
            if isinstance(snapshot, dict) and snapshot.get("quarantined") is True:
                return True
    return False


def _applied_fills(records: list[dict[str, object]], market_id: str) -> list[_AppliedFill]:
    fills: dict[str, NormalizedFill] = {}
    result: list[_AppliedFill] = []
    for record in records:
        event_type = record.get("event_type")
        payload = record.get("payload")
        if event_type == "normalized_fill" and isinstance(payload, dict):
            fill = NormalizedFill.from_payload(payload)
            if fill.market_id.lower() == market_id.lower():
                fills[str(record["event_id"])] = fill
            continue
        if event_type != "state_application" or not isinstance(payload, dict):
            continue
        if str(payload.get("market_id") or "").lower() != market_id.lower():
            continue
        if payload.get("status") != "applied":
            continue
        fill_event_id = str(payload["normalized_fill_event_id"])
        fill = fills.get(fill_event_id)
        if fill is None:
            raise ValueError(f"state application references missing fill {fill_event_id}")
        result.append(
            _AppliedFill(
                application_sequence=int(str(record["sequence"])),
                fill_event_id=fill_event_id,
                fill=fill,
            )
        )
    return result


def _feature_state(applied: list[_AppliedFill], event_epoch: int) -> _FeatureState:
    buys = [item.fill for item in applied if item.fill.side == "BUY"]
    up_inventory = sum(
        (fill.shares for fill in buys if fill.outcome_side == "UP"),
        start=ZERO,
    )
    down_inventory = sum(
        (fill.shares for fill in buys if fill.outcome_side == "DOWN"),
        start=ZERO,
    )
    paired = min(up_inventory, down_inventory)
    residual = abs(up_inventory - down_inventory)
    total = up_inventory + down_inventory
    imbalance = None if total == ZERO else (up_inventory - down_inventory) / total

    up_times = [fill.source_timestamp for fill in buys if fill.outcome_side == "UP"]
    down_times = [fill.source_timestamp for fill in buys if fill.outcome_side == "DOWN"]
    last_up = max(up_times, default=None)
    last_down = max(down_times, default=None)

    def trailing(seconds: int) -> tuple[int, Decimal]:
        cutoff = event_epoch - seconds
        selected = [
            fill for fill in buys if cutoff <= int(fill.source_timestamp.timestamp()) <= event_epoch
        ]
        return len(selected), sum((fill.shares for fill in selected), start=ZERO)

    count15, qty15 = trailing(15)
    count30, qty30 = trailing(30)
    count60, qty60 = trailing(60)
    trailing60 = sorted(
        (
            fill
            for fill in buys
            if event_epoch - 60 <= int(fill.source_timestamp.timestamp()) <= event_epoch
        ),
        key=lambda fill: (
            fill.source_timestamp,
            fill.source_trade_id,
            fill.local_ingest_id,
        ),
    )
    switches = sum(
        1
        for left, right in zip(trailing60, trailing60[1:], strict=False)
        if left.outcome_side != right.outcome_side
    )
    same_second = sum(1 for fill in buys if int(fill.source_timestamp.timestamp()) == event_epoch)
    max_source = max((fill.source_timestamp for fill in buys), default=None)
    max_key = max(
        ((fill.source_timestamp, fill.source_trade_id, fill.local_ingest_id) for fill in buys),
        default=None,
    )
    max_receive = max((fill.receive_timestamp for fill in buys), default=None)
    return _FeatureState(
        up_inventory=up_inventory,
        down_inventory=down_inventory,
        paired_inventory=paired,
        residual_inventory=residual,
        inventory_imbalance=imbalance,
        seconds_since_last_up_fill=_seconds_since(event_epoch, last_up),
        seconds_since_last_down_fill=_seconds_since(event_epoch, last_down),
        fill_count_15s=count15,
        fill_count_30s=count30,
        fill_count_60s=count60,
        fill_qty_15s=qty15,
        fill_qty_30s=qty30,
        fill_qty_60s=qty60,
        side_switches_60s=switches,
        cumulative_paired_quantity=paired,
        same_second_fill_count=same_second,
        max_source_timestamp=max_source,
        max_fill_key=max_key,
        max_receive_timestamp=max_receive,
    )


def _btc_model_values(btc: BtcFeatureRow) -> dict[str, object]:
    return {
        "btc_return_60s": _numeric(btc.return_60s),
        "btc_return_120s": _numeric(btc.return_120s),
        "btc_absolute_return_60s": _numeric(btc.absolute_return_60s),
        "btc_return_since_market_start": _numeric(btc.return_since_market_start),
        "btc_range_since_market_start": _numeric(btc.range_since_market_start),
    }


def _ordered_feature_vector(
    *,
    state: _FeatureState,
    btc: BtcFeatureRow,
    elapsed_seconds: int,
) -> dict[str, object]:
    values: dict[str, object] = {
        "elapsed_seconds": elapsed_seconds,
        "seconds_remaining": 300 - elapsed_seconds,
        "up_inventory": _numeric(state.up_inventory),
        "down_inventory": _numeric(state.down_inventory),
        "paired_inventory": _numeric(state.paired_inventory),
        "residual_inventory": _numeric(state.residual_inventory),
        "inventory_imbalance": _numeric(state.inventory_imbalance),
        "seconds_since_last_up_fill": state.seconds_since_last_up_fill,
        "seconds_since_last_down_fill": state.seconds_since_last_down_fill,
        "fill_count_15s": state.fill_count_15s,
        "fill_count_30s": state.fill_count_30s,
        "fill_count_60s": state.fill_count_60s,
        "fill_qty_15s": _numeric(state.fill_qty_15s),
        "fill_qty_30s": _numeric(state.fill_qty_30s),
        "fill_qty_60s": _numeric(state.fill_qty_60s),
        "side_switches_60s": state.side_switches_60s,
        "cumulative_paired_quantity": _numeric(state.cumulative_paired_quantity),
        "same_second_fill_count": state.same_second_fill_count,
        **_btc_model_values(btc),
    }
    if tuple(values) != PRIMARY_FEATURES:
        raise ValueError("live feature order does not match frozen Stage 3G primary model")
    return values


def _latest_btc_observation_time(
    records: list[dict[str, object]], reference_epoch: int
) -> datetime | None:
    latest: datetime | None = None
    for record in records:
        if record.get("event_type") != "btc_candle":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if int(str(payload.get("close_epoch"))) != reference_epoch:
            continue
        latest = _record_created_at(record)
    return latest


class LiveStage3GFeatureBuilder:
    """Build causal Stage 3G feature snapshots from only already-durable observations."""

    def __init__(self, *, run_id: str, store: AppendOnlyEventStore) -> None:
        self.run_id = run_id
        self.store = store

    def known_market_ids(self, *, as_of_sequence: int | None = None) -> list[str]:
        records = self._records(as_of_sequence)
        market_ids: set[str] = set()
        for record in records:
            if record.get("event_type") != "market_metadata":
                continue
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("eligible") is True:
                market_ids.add(str(payload.get("condition_id") or ""))
        return sorted(market_id for market_id in market_ids if market_id)

    def build_tick(
        self,
        *,
        market_id: str,
        tick_time: datetime,
        as_of_sequence: int | None = None,
    ) -> FeatureTickResult:
        tick_time = tick_time.astimezone(UTC)
        event_epoch = int(tick_time.timestamp())
        cutoff_sequence = (
            self.store.next_sequence() - 1 if as_of_sequence is None else as_of_sequence
        )
        records = self._records(cutoff_sequence)
        metadata = _market_metadata(records, market_id)
        if metadata is None:
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "market_metadata_unknown_or_ineligible",
            )
        elapsed = event_epoch - metadata.market_start_epoch
        if elapsed < 0 or elapsed >= 300:
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "outside_market_window",
            )
        if not (EVALUATION_START_HOUR_UTC <= tick_time.hour < EVALUATION_END_HOUR_UTC):
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "outside_evaluation_window",
            )
        if metadata.active is False or metadata.closed is True:
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "market_inactive_or_closed",
            )
        if _market_quarantined(records, market_id):
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "market_state_quarantined",
            )

        target_health = _latest_target_poll_ok(records)
        if target_health is None:
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "target_source_never_healthy",
            )
        target_age = max(0, event_epoch - int(target_health.timestamp()))
        if target_age > TARGET_HEALTH_MAX_AGE_SECONDS:
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "target_source_stale",
            )

        candles = load_latest_btc_candles(
            self.store,
            as_of_sequence=cutoff_sequence,
        )
        btc = build_btc_features(
            candles,
            event_epoch=event_epoch,
            market_start_epoch=metadata.market_start_epoch,
        )
        if btc.reference_epoch is None:
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "btc_no_causal_candle",
            )
        btc_age = event_epoch - btc.reference_epoch
        if btc_age > BTC_MAX_AGE_SECONDS:
            return self._unscorable(
                market_id,
                tick_time,
                cutoff_sequence,
                "btc_reference_stale",
            )

        applied = _applied_fills(records, market_id)
        state = _feature_state(applied, event_epoch)
        features = _ordered_feature_vector(
            state=state,
            btc=btc,
            elapsed_seconds=elapsed,
        )
        btc_observed_at = _latest_btc_observation_time(records, btc.reference_epoch)
        sequence = self.store.next_sequence()
        event_id = f"{self.run_id}:{sequence}"
        max_key = state.max_fill_key
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="feature_snapshot",
                event_id=event_id,
                run_id=self.run_id,
                sequence=sequence,
                created_at=tick_time,
                payload={
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "model_name": PRIMARY_MODEL_NAME,
                    "market_id": market_id,
                    "market_slug": metadata.slug,
                    "market_start_epoch": metadata.market_start_epoch,
                    "market_end_epoch": metadata.market_end_epoch,
                    "up_token_id": metadata.up_token_id,
                    "down_token_id": metadata.down_token_id,
                    "event_epoch": event_epoch,
                    "tick_timestamp": tick_time.isoformat(),
                    "as_of_sequence": cutoff_sequence,
                    "feature_order": list(PRIMARY_FEATURES),
                    "features": features,
                    "btc_reference_epoch": btc.reference_epoch,
                    "btc_reference_price": _numeric(btc.reference_price),
                    "btc_age_seconds": btc_age,
                    "btc_observed_at": (
                        None if btc_observed_at is None else btc_observed_at.isoformat()
                    ),
                    "target_source_last_ok": target_health.isoformat(),
                    "target_source_age_seconds": target_age,
                    "max_target_source_timestamp": (
                        None
                        if state.max_source_timestamp is None
                        else state.max_source_timestamp.astimezone(UTC).isoformat()
                    ),
                    "max_target_receive_timestamp": (
                        None
                        if state.max_receive_timestamp is None
                        else state.max_receive_timestamp.astimezone(UTC).isoformat()
                    ),
                    "max_deterministic_fill_key": (
                        None
                        if max_key is None
                        else [max_key[0].astimezone(UTC).isoformat(), max_key[1], max_key[2]]
                    ),
                    "applied_buy_fill_count": sum(1 for item in applied if item.fill.side == "BUY"),
                },
            )
        )
        return FeatureTickResult(market_id, True, event_id, None)

    def tick_known_markets(self, *, tick_time: datetime) -> list[FeatureTickResult]:
        cutoff_sequence = self.store.next_sequence() - 1
        return [
            self.build_tick(
                market_id=market_id,
                tick_time=tick_time,
                as_of_sequence=cutoff_sequence,
            )
            for market_id in self.known_market_ids(as_of_sequence=cutoff_sequence)
        ]

    async def run_forever(
        self,
        *,
        tick_interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS,
        clock: Clock = _utc_now,
    ) -> None:
        if tick_interval_seconds <= 0:
            raise ValueError("tick_interval_seconds must be positive")
        while True:
            started = asyncio.get_running_loop().time()
            self.tick_known_markets(tick_time=clock())
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, tick_interval_seconds - elapsed))

    def _records(self, as_of_sequence: int | None) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for record in self.store.iter_records():
            sequence = int(str(record["sequence"]))
            if as_of_sequence is not None and sequence > as_of_sequence:
                break
            records.append(record)
        return records

    def _unscorable(
        self,
        market_id: str,
        tick_time: datetime,
        as_of_sequence: int,
        reason_code: str,
    ) -> FeatureTickResult:
        sequence = self.store.next_sequence()
        event_id = f"{self.run_id}:{sequence}"
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="unscorable_tick",
                event_id=event_id,
                run_id=self.run_id,
                sequence=sequence,
                created_at=tick_time,
                payload={
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "model_name": PRIMARY_MODEL_NAME,
                    "market_id": market_id,
                    "tick_timestamp": tick_time.isoformat(),
                    "event_epoch": int(tick_time.timestamp()),
                    "as_of_sequence": as_of_sequence,
                    "reason_code": reason_code,
                },
            )
        )
        return FeatureTickResult(market_id, False, event_id, reason_code)
