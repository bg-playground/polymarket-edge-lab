from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from polymarket_edge_lab.shadow.store import AppendOnlyEventStore
from polymarket_edge_lab.shadow.target_collector import LiveTargetAccountCollector

ACCOUNT = "0xbf337426aa856996b8bb79b238345dd1a0276bf7"


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=10)
        return current


def _trade() -> dict[str, object]:
    return {
        "proxyWallet": ACCOUNT,
        "side": "BUY",
        "asset": "asset-up",
        "conditionId": "0x" + "1" * 64,
        "size": 2.5,
        "price": 0.44,
        "timestamp": 1786795200,
        "title": "Bitcoin Up or Down",
        "slug": "btc-updown-5m",
        "eventSlug": "btc-updown",
        "outcome": "Up",
        "outcomeIndex": 0,
        "transactionHash": "0xabc",
    }


@pytest.mark.asyncio
async def test_poll_persists_exact_raw_bytes_before_normalized_fill(tmp_path: Path) -> None:
    raw = json.dumps([_trade()], separators=(",", ":")).encode()
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, content=raw, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AppendOnlyEventStore(tmp_path / "events.ndjson")
        collector = LiveTargetAccountCollector(
            account=ACCOUNT,
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        result = await collector.poll_once()

    assert result.normalized_fill_count == 1
    assert seen_request is not None
    assert seen_request.url.params["user"] == ACCOUNT
    assert seen_request.url.params["takerOnly"] == "false"
    records = list(store.iter_records())
    assert [record["event_type"] for record in records] == [
        "raw_observation",
        "normalized_fill",
        "source_health",
    ]
    raw_payload = records[0]["payload"]
    assert isinstance(raw_payload, dict)
    assert base64.b64decode(str(raw_payload["response_body_b64"])) == raw
    normalized_payload = records[1]["payload"]
    assert isinstance(normalized_payload, dict)
    assert normalized_payload["raw_observation_event_id"] == records[0]["event_id"]
    assert normalized_payload["outcome_side"] == "UP"


@pytest.mark.asyncio
async def test_overlapping_poll_deduplicates_normalized_fill_across_restart(tmp_path: Path) -> None:
    raw = json.dumps([_trade()], separators=(",", ":")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, request=request)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = LiveTargetAccountCollector(
            account=ACCOUNT,
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        assert (await first.poll_once()).normalized_fill_count == 1
        restarted = LiveTargetAccountCollector(
            account=ACCOUNT,
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        result = await restarted.poll_once()

    assert result.normalized_fill_count == 0
    assert result.duplicate_fill_count == 1
    types = [record["event_type"] for record in store.iter_records()]
    assert types.count("raw_observation") == 2
    assert types.count("normalized_fill") == 1


@pytest.mark.asyncio
async def test_http_error_body_is_durable_before_failure(tmp_path: Path) -> None:
    raw = b'{"error":"temporary"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=raw, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AppendOnlyEventStore(tmp_path / "events.ndjson")
        collector = LiveTargetAccountCollector(
            account=ACCOUNT,
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await collector.poll_once()

    records = list(store.iter_records())
    assert [record["event_type"] for record in records] == ["raw_observation", "source_health"]
    payload = records[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["http_status"] == 503
    assert base64.b64decode(str(payload["response_body_b64"])) == raw
