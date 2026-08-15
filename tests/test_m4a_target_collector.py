from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from polymarket_edge_lab.shadow.market_metadata import (
    EligibleMarketMetadata,
    MarketMetadataResult,
)
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore
from polymarket_edge_lab.shadow.target_collector import LiveTargetAccountCollector

ACCOUNT = "0xbf337426aa856996b8bb79b238345dd1a0276bf7"
CONDITION_ID = "0x" + "1" * 64
START = 1_786_795_200


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=10)
        return current


class _MetadataResolver:
    def __init__(self, result: MarketMetadataResult) -> None:
        self.result = result
        self.calls = 0

    async def resolve(self, condition_id: str) -> MarketMetadataResult:
        self.calls += 1
        assert condition_id == CONDITION_ID
        return self.result


def _eligible_result() -> MarketMetadataResult:
    return MarketMetadataResult(
        condition_id=CONDITION_ID,
        eligible=True,
        reason_code="eligible",
        metadata=EligibleMarketMetadata(
            condition_id=CONDITION_ID,
            gamma_market_id="123",
            slug=f"btc-updown-5m-{START}",
            question="Bitcoin Up or Down",
            market_start_epoch=START,
            market_end_epoch=START + 300,
            up_token_id="asset-up",
            down_token_id="asset-down",
            active=True,
            closed=False,
            accepting_orders=True,
            raw_observation_sha256="a" * 64,
        ),
    )


def _trade(*, asset: str = "asset-up", outcome: str = "Up") -> dict[str, object]:
    return {
        "proxyWallet": ACCOUNT,
        "side": "BUY",
        "asset": asset,
        "conditionId": CONDITION_ID,
        "size": 2.5,
        "price": 0.44,
        "timestamp": 1786795200,
        "title": "Bitcoin Up or Down",
        "slug": "btc-updown-5m",
        "eventSlug": "btc-updown",
        "outcome": outcome,
        "outcomeIndex": 0,
        "transactionHash": "0xabc",
    }


def _collector(
    *,
    store: AppendOnlyEventStore,
    client: httpx.AsyncClient,
    resolver: _MetadataResolver,
) -> LiveTargetAccountCollector:
    return LiveTargetAccountCollector(  # type: ignore[arg-type]
        account=ACCOUNT,
        run_id="run-live",
        store=store,
        metadata_resolver=resolver,
        client=client,
        clock=_Clock(),
    )


@pytest.mark.asyncio
async def test_poll_persists_raw_then_admission_then_normalized_fill(tmp_path: Path) -> None:
    raw = json.dumps([_trade()], separators=(",", ":")).encode()
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, content=raw, request=request)

    resolver = _MetadataResolver(_eligible_result())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AppendOnlyEventStore(tmp_path / "events.ndjson")
        result = await _collector(store=store, client=client, resolver=resolver).poll_once()

    assert result.normalized_fill_count == 1
    assert seen_request is not None
    assert seen_request.url.params["user"] == ACCOUNT
    assert seen_request.url.params["takerOnly"] == "false"
    records = list(store.iter_records())
    assert [record["event_type"] for record in records] == [
        "raw_observation",
        "fill_admission",
        "normalized_fill",
        "source_health",
    ]
    admission = records[1]["payload"]
    assert isinstance(admission, dict)
    assert admission["admitted"] is True
    assert admission["outcome_side"] == "UP"
    normalized_payload = records[2]["payload"]
    assert isinstance(normalized_payload, dict)
    assert normalized_payload["fill_admission_event_id"] == records[1]["event_id"]
    assert normalized_payload["outcome_side"] == "UP"
    assert normalized_payload["market_metadata_sha256"] == "a" * 64


@pytest.mark.asyncio
async def test_token_mapping_overrides_textual_outcome_and_records_disagreement(
    tmp_path: Path,
) -> None:
    raw = json.dumps([_trade(outcome="Down")], separators=(",", ":")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, request=request)

    resolver = _MetadataResolver(_eligible_result())
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _collector(store=store, client=client, resolver=resolver).poll_once()

    assert result.normalized_fill_count == 1
    assert result.outcome_disagreement_count == 1
    records = list(store.iter_records())
    normalized = next(record for record in records if record["event_type"] == "normalized_fill")
    payload = normalized["payload"]
    assert isinstance(payload, dict)
    assert payload["outcome_side"] == "UP"
    health = [record for record in records if record["event_type"] == "source_health"]
    assert any(
        isinstance(record["payload"], dict)
        and record["payload"].get("status") == "outcome_mapping_disagreement"
        for record in health
    )


@pytest.mark.asyncio
async def test_unknown_asset_is_durably_rejected_and_deduplicated_after_restart(
    tmp_path: Path,
) -> None:
    raw = json.dumps([_trade(asset="unknown-token")], separators=(",", ":")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, request=request)

    resolver = _MetadataResolver(_eligible_result())
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await _collector(store=store, client=client, resolver=resolver).poll_once()
        second = await _collector(store=store, client=client, resolver=resolver).poll_once()

    assert first.normalized_fill_count == 0
    assert first.unmapped_asset_count == 1
    assert second.duplicate_fill_count == 1
    admissions = [
        record for record in store.iter_records() if record["event_type"] == "fill_admission"
    ]
    assert len(admissions) == 1
    payload = admissions[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["admitted"] is False
    assert payload["reason_code"] == "asset_not_in_durable_token_mapping"


@pytest.mark.asyncio
async def test_ineligible_market_is_durably_rejected(tmp_path: Path) -> None:
    raw = json.dumps([_trade()], separators=(",", ":")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, request=request)

    resolver = _MetadataResolver(
        MarketMetadataResult(
            condition_id=CONDITION_ID,
            eligible=False,
            reason_code="not_stage3g_btc_5m_slug",
            metadata=None,
        )
    )
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _collector(store=store, client=client, resolver=resolver).poll_once()

    assert result.normalized_fill_count == 0
    assert result.ineligible_fill_count == 1
    assert not any(record["event_type"] == "normalized_fill" for record in store.iter_records())


@pytest.mark.asyncio
async def test_http_error_body_is_durable_before_failure(tmp_path: Path) -> None:
    raw = b'{"error":"temporary"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=raw, request=request)

    resolver = _MetadataResolver(_eligible_result())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AppendOnlyEventStore(tmp_path / "events.ndjson")
        with pytest.raises(httpx.HTTPStatusError):
            await _collector(store=store, client=client, resolver=resolver).poll_once()

    records = list(store.iter_records())
    assert [record["event_type"] for record in records] == [
        "raw_observation",
        "source_health",
    ]
    payload = records[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["http_status"] == 503
    raw_path = tmp_path / str(payload["raw_body_path"])
    assert raw_path.read_bytes() == raw


@pytest.mark.asyncio
async def test_transport_failure_is_recorded_as_source_health(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    resolver = _MetadataResolver(_eligible_result())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AppendOnlyEventStore(tmp_path / "events.ndjson")
        with pytest.raises(httpx.ConnectError):
            await _collector(store=store, client=client, resolver=resolver).poll_once()

    records = list(store.iter_records())
    assert len(records) == 1
    assert records[0]["event_type"] == "source_health"
    payload = records[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["status"] == "transport_failed"
