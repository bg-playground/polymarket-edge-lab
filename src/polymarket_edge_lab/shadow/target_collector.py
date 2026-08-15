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

from polymarket_edge_lab.normalization.trades import normalize_records
from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

DATA_API_BASE = "https://data-api.polymarket.com"
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_PAGE_LIMIT = 500

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class PollResult:
    raw_event_id: str
    http_status: int
    response_sha256: str
    raw_record_count: int
    normalized_fill_count: int
    duplicate_fill_count: int
    rejected_record_count: int


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _event_id(run_id: str, sequence: int) -> str:
    return f"{run_id}:{sequence}"


class LiveTargetAccountCollector:
    """Read-only Data API collector with durable append-before-normalize storage."""

    def __init__(
        self,
        *,
        account: str,
        run_id: str,
        store: AppendOnlyEventStore,
        client: httpx.AsyncClient | None = None,
        base_url: str = DATA_API_BASE,
        page_limit: int = DEFAULT_PAGE_LIMIT,
        raw_archive_dir: Path | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self.account = account.lower()
        self.run_id = run_id
        self.store = store
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._page_limit = page_limit
        self._clock = clock
        self._raw_archive_dir = raw_archive_dir or (
            store.path.parent / "raw" / "polymarket_data_api"
        )
        self._raw_archive_dir.mkdir(parents=True, exist_ok=True)
        self._seen_source_trade_ids = self._load_seen_source_trade_ids()

    def _load_seen_source_trade_ids(self) -> set[str]:
        seen: set[str] = set()
        for record in self.store.iter_records():
            if record.get("event_type") != "normalized_fill":
                continue
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("source_trade_id") is not None:
                seen.add(str(payload["source_trade_id"]))
        return seen

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
                raise ValueError(
                    f"raw archive hash collision or corruption at {path}"
                ) from exc
        return path

    async def poll_once(self) -> PollResult:
        request_start = self._clock()
        params: dict[str, str | int] = {
            "user": self.account,
            "offset": 0,
            "limit": self._page_limit,
            "takerOnly": "false",
        }
        url = f"{self._base_url}/trades"
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
        relative_raw_path = raw_path.relative_to(self.store.path.parent)
        raw_sequence = self.store.next_sequence()
        raw_event_id = _event_id(self.run_id, raw_sequence)
        raw_payload: dict[str, object] = {
            "source": "polymarket-data-api",
            "endpoint": url,
            "request_params": dict(params),
            "request_start": request_start.astimezone(UTC).isoformat(),
            "response_receive": response_receive.astimezone(UTC).isoformat(),
            "request_attempt": 1,
            "retry_count": 0,
            "http_status": response.status_code,
            "response_sha256": response_sha256,
            "raw_body_path": str(relative_raw_path),
            "raw_body_size": len(raw_bytes),
        }
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="raw_observation",
                event_id=raw_event_id,
                run_id=self.run_id,
                sequence=raw_sequence,
                created_at=response_receive,
                payload=raw_payload,
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
        parse_complete = self._clock()
        if not isinstance(payload, list):
            self._append_source_health(
                status="parse_failed",
                detail=f"expected list payload, got {type(payload).__name__}",
                observed_at=parse_complete,
                raw_event_id=raw_event_id,
            )
            raise TypeError(f"expected list payload, got {type(payload).__name__}")
        raw_records = [record for record in payload if isinstance(record, dict)]
        if len(raw_records) != len(payload):
            self._append_source_health(
                status="parse_failed",
                detail="trade payload contains a non-object record",
                observed_at=parse_complete,
                raw_event_id=raw_event_id,
            )
            raise TypeError("trade payload contains a non-object record")

        for record in raw_records:
            wallet = str(record.get("proxyWallet", "")).lower()
            if wallet and wallet != self.account:
                detail = (
                    f"Data API returned proxyWallet {wallet} for requested "
                    f"account {self.account}"
                )
                self._append_source_health(
                    status="account_mismatch",
                    detail=detail,
                    observed_at=self._clock(),
                    raw_event_id=raw_event_id,
                )
                raise ValueError(detail)

        normalized = normalize_records(raw_records, account=self.account)
        normalize_complete = self._clock()
        new_fill_count = 0
        duplicate_fill_count = 0
        for trade in normalized.accepted:
            if trade.source_trade_id in self._seen_source_trade_ids:
                duplicate_fill_count += 1
                continue
            outcome = trade.outcome.strip().upper()
            if outcome not in {"UP", "DOWN"}:
                continue
            fill = NormalizedFill(
                source_trade_id=trade.source_trade_id,
                market_id=trade.market_id,
                asset_id=trade.asset_id,
                outcome_side=outcome,  # type: ignore[arg-type]
                side=trade.side,
                source_timestamp=trade.timestamp,
                price=trade.price,
                shares=trade.shares,
                receive_timestamp=response_receive,
                local_ingest_id=(
                    f"{raw_event_id}:{trade.raw_extra.get('_record_index', 0)}"
                ),
            )
            sequence = self.store.next_sequence()
            payload_record = fill.to_payload()
            payload_record.update(
                {
                    "raw_observation_event_id": raw_event_id,
                    "response_sha256": response_sha256,
                    "parse_complete": parse_complete.astimezone(UTC).isoformat(),
                    "normalize_complete": normalize_complete.astimezone(UTC).isoformat(),
                }
            )
            self.store.append(
                EventEnvelope(
                    schema_version="m4a-event-v1",
                    event_type="normalized_fill",
                    event_id=_event_id(self.run_id, sequence),
                    run_id=self.run_id,
                    sequence=sequence,
                    created_at=normalize_complete,
                    payload=payload_record,
                )
            )
            self._seen_source_trade_ids.add(trade.source_trade_id)
            new_fill_count += 1

        self._append_source_health(
            status="poll_ok",
            detail=f"records={len(raw_records)} new_fills={new_fill_count}",
            observed_at=normalize_complete,
            raw_event_id=raw_event_id,
        )
        return PollResult(
            raw_event_id=raw_event_id,
            http_status=response.status_code,
            response_sha256=response_sha256,
            raw_record_count=len(raw_records),
            normalized_fill_count=new_fill_count,
            duplicate_fill_count=duplicate_fill_count,
            rejected_record_count=len(normalized.rejected),
        )

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
                    "source": "polymarket-data-api",
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
