from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

from polymarket_edge_lab.analysis.btc_features import BtcCandle
from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

COINBASE_EXCHANGE_API_BASE = "https://api.exchange.coinbase.com"
PRODUCT_ID = "BTC-USD"
GRANULARITY_SECONDS = 60
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
OVERLAP_SECONDS = 180

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class BtcPollResult:
    raw_event_id: str
    http_status: int
    response_sha256: str
    returned_candle_count: int
    causal_candle_count: int
    new_candle_count: int
    revised_candle_count: int
    duplicate_candle_count: int


@dataclass(frozen=True)
class _DurableCandle:
    event_id: str
    fingerprint: str


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _event_id(run_id: str, sequence: int) -> str:
    return f"{run_id}:{sequence}"


def _floor_minute(epoch: int) -> int:
    return epoch - epoch % GRANULARITY_SECONDS


def _fingerprint(candle: BtcCandle, volume: Decimal) -> str:
    payload = "|".join(
        (
            str(candle.open_epoch),
            str(candle.open),
            str(candle.high),
            str(candle.low),
            str(candle.close),
            str(volume),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _parse_candle_row(row: object) -> tuple[BtcCandle, Decimal]:
    if not isinstance(row, list) or len(row) < 6:
        raise ValueError("Coinbase candle row must contain at least six values")
    open_epoch = int(row[0])
    low = Decimal(str(row[1]))
    high = Decimal(str(row[2]))
    open_price = Decimal(str(row[3]))
    close = Decimal(str(row[4]))
    volume = Decimal(str(row[5]))
    if open_epoch % GRANULARITY_SECONDS != 0:
        raise ValueError(f"Coinbase candle open epoch is not 60-second aligned: {open_epoch}")
    if min(low, high, open_price, close, volume) < Decimal("0"):
        raise ValueError("Coinbase candle values must be non-negative")
    if high < low:
        raise ValueError("Coinbase candle high is below low")
    return (
        BtcCandle(
            open_epoch=open_epoch,
            open=open_price,
            high=high,
            low=low,
            close=close,
            interval_seconds=GRANULARITY_SECONDS,
        ),
        volume,
    )


def _candle_from_payload(payload: dict[str, object]) -> BtcCandle:
    return BtcCandle(
        open_epoch=int(str(payload["open_epoch"])),
        open=Decimal(str(payload["open"])),
        high=Decimal(str(payload["high"])),
        low=Decimal(str(payload["low"])),
        close=Decimal(str(payload["close"])),
        interval_seconds=int(str(payload["interval_seconds"])),
    )


def load_latest_btc_candles(
    store: AppendOnlyEventStore, *, as_of_sequence: int | None = None
) -> list[BtcCandle]:
    """Rebuild the latest BTC candle version known by a durable append sequence."""
    latest: dict[int, BtcCandle] = {}
    for record in store.iter_records():
        sequence = int(str(record["sequence"]))
        if as_of_sequence is not None and sequence > as_of_sequence:
            break
        if record.get("event_type") != "btc_candle":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("btc_candle payload must be an object")
        candle = _candle_from_payload(payload)
        if candle.interval_seconds != GRANULARITY_SECONDS:
            raise ValueError("durable BTC candle does not use frozen 60-second resolution")
        latest[candle.open_epoch] = candle
    return [latest[epoch] for epoch in sorted(latest)]


class LiveBtc60Collector:
    """Read-only Coinbase Exchange collector for closed BTC-USD 60-second candles."""

    def __init__(
        self,
        *,
        run_id: str,
        store: AppendOnlyEventStore,
        client: httpx.AsyncClient | None = None,
        base_url: str = COINBASE_EXCHANGE_API_BASE,
        raw_archive_dir: Path | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self.run_id = run_id
        self.store = store
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._clock = clock
        self._raw_archive_dir = raw_archive_dir or (
            store.path.parent / "raw" / "coinbase_btc_usd_candles"
        )
        self._raw_archive_dir.mkdir(parents=True, exist_ok=True)
        self._durable = self._load_durable_candles()

    def _load_durable_candles(self) -> dict[int, _DurableCandle]:
        durable: dict[int, _DurableCandle] = {}
        for record in self.store.iter_records():
            if record.get("event_type") != "btc_candle":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            open_epoch = int(str(payload["open_epoch"]))
            durable[open_epoch] = _DurableCandle(
                event_id=str(record["event_id"]),
                fingerprint=str(payload["candle_fingerprint"]),
            )
        return durable

    def _persist_raw_bytes(self, raw_bytes: bytes, response_sha256: str) -> Path:
        path = self._raw_archive_dir / f"{response_sha256}.bin"
        if path.exists():
            if path.read_bytes() != raw_bytes:
                raise ValueError(f"raw archive hash collision or corruption at {path}")
            return path
        try:
            with path.open("xb") as handle:
                handle.write(raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            if path.read_bytes() != raw_bytes:
                raise ValueError(f"raw archive hash collision or corruption at {path}") from exc
        return path

    async def poll_once(self) -> BtcPollResult:
        request_start = self._clock()
        request_epoch = int(request_start.timestamp())
        closed_boundary = _floor_minute(request_epoch)
        start = datetime.fromtimestamp(closed_boundary - OVERLAP_SECONDS, tz=UTC)
        end = datetime.fromtimestamp(closed_boundary, tz=UTC)
        params = {
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "granularity": str(GRANULARITY_SECONDS),
        }
        url = f"{self._base_url}/products/{PRODUCT_ID}/candles"
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, params=params)
            else:
                response = await self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            self._append_source_health(
                status="transport_failed",
                detail=f"{type(exc).__name__}: {exc}",
                observed_at=self._clock(),
                raw_event_id=None,
            )
            raise

        response_receive = self._clock()
        raw_bytes = response.content
        response_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        raw_path = self._persist_raw_bytes(raw_bytes, response_sha256)
        raw_sequence = self.store.next_sequence()
        raw_event_id = _event_id(self.run_id, raw_sequence)
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="raw_observation",
                event_id=raw_event_id,
                run_id=self.run_id,
                sequence=raw_sequence,
                created_at=response_receive,
                payload={
                    "source": "coinbase-exchange-rest",
                    "product_id": PRODUCT_ID,
                    "endpoint": url,
                    "request_params": params,
                    "request_start": request_start.astimezone(UTC).isoformat(),
                    "response_receive": response_receive.astimezone(UTC).isoformat(),
                    "http_status": response.status_code,
                    "response_sha256": response_sha256,
                    "raw_body_path": str(raw_path.relative_to(self.store.path.parent)),
                    "raw_body_size": len(raw_bytes),
                },
            )
        )

        if response.status_code < 200 or response.status_code >= 300:
            self._append_source_health(
                status="request_failed",
                detail=f"HTTP {response.status_code}",
                observed_at=response_receive,
                raw_event_id=raw_event_id,
            )
            response.raise_for_status()

        try:
            payload = json.loads(raw_bytes, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            self._append_source_health(
                status="parse_failed",
                detail=f"JSONDecodeError: {exc}",
                observed_at=self._clock(),
                raw_event_id=raw_event_id,
            )
            raise
        if not isinstance(payload, list):
            raise TypeError("Coinbase candles response must be a list")

        receive_epoch = int(response_receive.timestamp())
        parsed = [_parse_candle_row(row) for row in payload]
        causal = [
            item for item in parsed if item[0].close_epoch <= receive_epoch
        ]
        new_count = 0
        revised_count = 0
        duplicate_count = 0
        for candle, volume in sorted(causal, key=lambda item: item[0].open_epoch):
            fingerprint = _fingerprint(candle, volume)
            prior = self._durable.get(candle.open_epoch)
            if prior is not None and prior.fingerprint == fingerprint:
                duplicate_count += 1
                continue
            supersedes = None if prior is None else prior.event_id
            event_id = self._append_candle(
                candle=candle,
                volume=volume,
                fingerprint=fingerprint,
                observed_at=response_receive,
                raw_event_id=raw_event_id,
                response_sha256=response_sha256,
                supersedes_event_id=supersedes,
            )
            self._durable[candle.open_epoch] = _DurableCandle(event_id, fingerprint)
            if prior is None:
                new_count += 1
            else:
                revised_count += 1

        self._append_source_health(
            status="poll_ok",
            detail=(
                f"returned={len(parsed)} causal={len(causal)} new={new_count} "
                f"revised={revised_count} duplicate={duplicate_count}"
            ),
            observed_at=response_receive,
            raw_event_id=raw_event_id,
        )
        return BtcPollResult(
            raw_event_id=raw_event_id,
            http_status=response.status_code,
            response_sha256=response_sha256,
            returned_candle_count=len(parsed),
            causal_candle_count=len(causal),
            new_candle_count=new_count,
            revised_candle_count=revised_count,
            duplicate_candle_count=duplicate_count,
        )

    def _append_candle(
        self,
        *,
        candle: BtcCandle,
        volume: Decimal,
        fingerprint: str,
        observed_at: datetime,
        raw_event_id: str,
        response_sha256: str,
        supersedes_event_id: str | None,
    ) -> str:
        sequence = self.store.next_sequence()
        event_id = _event_id(self.run_id, sequence)
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="btc_candle",
                event_id=event_id,
                run_id=self.run_id,
                sequence=sequence,
                created_at=observed_at,
                supersedes_event_id=supersedes_event_id,
                payload={
                    "source": "coinbase-exchange-rest",
                    "product_id": PRODUCT_ID,
                    "open_epoch": candle.open_epoch,
                    "close_epoch": candle.close_epoch,
                    "interval_seconds": candle.interval_seconds,
                    "open": str(candle.open),
                    "high": str(candle.high),
                    "low": str(candle.low),
                    "close": str(candle.close),
                    "volume": str(volume),
                    "candle_fingerprint": fingerprint,
                    "raw_observation_event_id": raw_event_id,
                    "response_sha256": response_sha256,
                    "causal_at_observation": candle.close_epoch <= int(observed_at.timestamp()),
                },
            )
        )
        return event_id

    def _append_source_health(
        self,
        *,
        status: str,
        detail: str,
        observed_at: datetime,
        raw_event_id: str | None,
    ) -> None:
        sequence = self.store.next_sequence()
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="source_health",
                event_id=_event_id(self.run_id, sequence),
                run_id=self.run_id,
                sequence=sequence,
                created_at=observed_at,
                payload={
                    "source": "coinbase-exchange-rest",
                    "status": status,
                    "detail": detail,
                    "raw_observation_event_id": raw_event_id,
                },
            )
        )

    async def run_forever(
        self, *, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await self.poll_once()
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
                pass
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, poll_interval_seconds - elapsed))
