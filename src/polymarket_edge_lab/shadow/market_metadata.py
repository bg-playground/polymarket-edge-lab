from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
_BTC_5M_RE = re.compile(r"^btc-updown-5m-(\d+)$")


@dataclass(frozen=True)
class EligibleMarketMetadata:
    condition_id: str
    gamma_market_id: str
    slug: str
    question: str | None
    market_start_epoch: int
    market_end_epoch: int
    up_token_id: str
    down_token_id: str
    active: bool | None
    closed: bool | None
    accepting_orders: bool | None
    raw_observation_sha256: str

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MarketMetadataResult:
    condition_id: str
    eligible: bool
    reason_code: str
    metadata: EligibleMarketMetadata | None


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _parse_string_array(value: object, field: str) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} is not valid JSON") from exc
    else:
        parsed = value
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError(f"{field} must be a string array")
    return [str(item) for item in parsed]


def classify_gamma_market(
    record: dict[str, Any], *, response_sha256: str
) -> MarketMetadataResult:
    condition_id = str(record.get("conditionId") or "")
    slug = str(record.get("slug") or "")
    match = _BTC_5M_RE.fullmatch(slug)
    if match is None:
        return MarketMetadataResult(condition_id, False, "not_stage3g_btc_5m_slug", None)

    try:
        outcomes = _parse_string_array(record.get("outcomes"), "outcomes")
        token_ids = _parse_string_array(record.get("clobTokenIds"), "clobTokenIds")
    except ValueError:
        return MarketMetadataResult(condition_id, False, "invalid_outcome_token_arrays", None)

    if len(outcomes) != 2 or len(token_ids) != 2:
        return MarketMetadataResult(condition_id, False, "not_binary_two_token_market", None)
    normalized = [outcome.strip().upper() for outcome in outcomes]
    if sorted(normalized) != ["DOWN", "UP"]:
        return MarketMetadataResult(condition_id, False, "outcomes_not_unambiguous_up_down", None)
    if len(set(token_ids)) != 2 or any(not token for token in token_ids):
        return MarketMetadataResult(condition_id, False, "invalid_or_duplicate_token_ids", None)

    mapping = dict(zip(normalized, token_ids, strict=True))
    market_start = int(match.group(1))
    metadata = EligibleMarketMetadata(
        condition_id=condition_id,
        gamma_market_id=str(record.get("id") or ""),
        slug=slug,
        question=str(record["question"]) if record.get("question") is not None else None,
        market_start_epoch=market_start,
        market_end_epoch=market_start + 300,
        up_token_id=mapping["UP"],
        down_token_id=mapping["DOWN"],
        active=record.get("active") if isinstance(record.get("active"), bool) else None,
        closed=record.get("closed") if isinstance(record.get("closed"), bool) else None,
        accepting_orders=(
            record.get("acceptingOrders")
            if isinstance(record.get("acceptingOrders"), bool)
            else None
        ),
        raw_observation_sha256=response_sha256,
    )
    return MarketMetadataResult(condition_id, True, "eligible", metadata)


class LiveMarketMetadataResolver:
    """Resolve and durably record Gamma metadata for observed condition IDs."""

    def __init__(
        self,
        *,
        run_id: str,
        store: AppendOnlyEventStore,
        client: httpx.AsyncClient | None = None,
        base_url: str = GAMMA_API_BASE,
        raw_archive_dir: Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.store = store
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._raw_archive_dir = raw_archive_dir or (
            store.path.parent / "raw" / "polymarket_gamma_markets"
        )
        self._raw_archive_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, MarketMetadataResult] = {}

    async def resolve(self, condition_id: str) -> MarketMetadataResult:
        key = condition_id.lower()
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        url = f"{self._base_url}/markets"
        params = {"condition_ids": condition_id}
        request_start = _utc_now()
        if self._client is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
        else:
            response = await self._client.get(url, params=params)
        response_receive = _utc_now()
        raw_bytes = response.content
        digest = hashlib.sha256(raw_bytes).hexdigest()
        raw_path = self._persist_raw_bytes(raw_bytes, digest)
        self._append_raw_observation(
            condition_id=condition_id,
            url=url,
            params=params,
            request_start=request_start,
            response_receive=response_receive,
            response=response,
            digest=digest,
            raw_path=raw_path,
        )
        response.raise_for_status()

        payload = json.loads(raw_bytes)
        if not isinstance(payload, list):
            raise TypeError("Gamma /markets response must be a list")
        matches = [
            record
            for record in payload
            if isinstance(record, dict)
            and str(record.get("conditionId") or "").lower() == key
        ]
        if len(matches) != 1:
            result = MarketMetadataResult(condition_id, False, "condition_lookup_not_unique", None)
        else:
            result = classify_gamma_market(matches[0], response_sha256=digest)
        self._append_market_metadata(result, response_receive)
        self._cache[key] = result
        return result

    def _persist_raw_bytes(self, raw_bytes: bytes, digest: str) -> Path:
        path = self._raw_archive_dir / f"{digest}.bin"
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

    def _append_raw_observation(
        self,
        *,
        condition_id: str,
        url: str,
        params: dict[str, str],
        request_start: datetime,
        response_receive: datetime,
        response: httpx.Response,
        digest: str,
        raw_path: Path,
    ) -> None:
        sequence = self.store.next_sequence()
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="raw_observation",
                event_id=f"{self.run_id}:{sequence}",
                run_id=self.run_id,
                sequence=sequence,
                created_at=response_receive,
                payload={
                    "source": "polymarket-gamma-api",
                    "endpoint": url,
                    "request_params": params,
                    "condition_id": condition_id,
                    "request_start": request_start.astimezone(UTC).isoformat(),
                    "response_receive": response_receive.astimezone(UTC).isoformat(),
                    "http_status": response.status_code,
                    "response_sha256": digest,
                    "raw_body_path": str(raw_path.relative_to(self.store.path.parent)),
                    "raw_body_size": len(response.content),
                },
            )
        )

    def _append_market_metadata(self, result: MarketMetadataResult, observed_at: datetime) -> None:
        sequence = self.store.next_sequence()
        payload: dict[str, object] = {
            "condition_id": result.condition_id,
            "eligible": result.eligible,
            "reason_code": result.reason_code,
        }
        if result.metadata is not None:
            payload["metadata"] = result.metadata.to_payload()
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="market_metadata",
                event_id=f"{self.run_id}:{sequence}",
                run_id=self.run_id,
                sequence=sequence,
                created_at=observed_at,
                payload=payload,
            )
        )
