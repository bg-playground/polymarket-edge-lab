from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from polymarket_edge_lab.shadow.btc_collector import (
    LiveBtc60Collector,
    load_latest_btc_candles,
)
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

BASE = datetime(2026, 8, 15, 12, 3, 5, tzinfo=UTC)


class _Clock:
    def __init__(self, start: datetime = BASE) -> None:
        self.value = start

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=10)
        return current


def _rows(*, revised_close: str | None = None) -> bytes:
    close = revised_close or "60100.25"
    rows = [
        [1786795260, 60000.0, 60200.0, 60050.0, close, 12.5],
        [1786795320, 60090.0, 60300.0, 60100.0, 60250.0, 9.25],
        [1786795380, 60200.0, 60400.0, 60250.0, 60350.0, 8.0],
    ]
    return json.dumps(rows, separators=(",", ":")).encode()


@pytest.mark.asyncio
async def test_poll_persists_raw_then_only_closed_causal_candles(tmp_path: Path) -> None:
    raw = _rows()
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, content=raw, request=request)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = LiveBtc60Collector(
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        result = await collector.poll_once()

    assert seen_request is not None
    assert seen_request.url.path.endswith("/products/BTC-USD/candles")
    assert seen_request.url.params["granularity"] == "60"
    assert result.returned_candle_count == 3
    assert result.causal_candle_count == 2
    assert result.new_candle_count == 2
    records = list(store.iter_records())
    assert records[0]["event_type"] == "raw_observation"
    candles = [record for record in records if record["event_type"] == "btc_candle"]
    assert len(candles) == 2
    for record in candles:
        payload = record["payload"]
        assert isinstance(payload, dict)
        assert payload["interval_seconds"] == 60
        assert payload["close_epoch"] == payload["open_epoch"] + 60
        assert payload["causal_at_observation"] is True
        assert payload["raw_observation_event_id"] == records[0]["event_id"]
    raw_payload = records[0]["payload"]
    assert isinstance(raw_payload, dict)
    raw_path = tmp_path / str(raw_payload["raw_body_path"])
    assert raw_path.read_bytes() == raw
    durable = load_latest_btc_candles(store)
    assert [candle.open_epoch for candle in durable] == [1786795260, 1786795320]
    assert all(candle.interval_seconds == 60 for candle in durable)


@pytest.mark.asyncio
async def test_overlapping_poll_is_restart_idempotent(tmp_path: Path) -> None:
    raw = _rows()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, request=request)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = LiveBtc60Collector(
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        assert (await first.poll_once()).new_candle_count == 2
        restarted = LiveBtc60Collector(
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        result = await restarted.poll_once()

    assert result.new_candle_count == 0
    assert result.revised_candle_count == 0
    assert result.duplicate_candle_count == 2
    records = list(store.iter_records())
    assert sum(record["event_type"] == "btc_candle" for record in records) == 2
    assert sum(record["event_type"] == "raw_observation" for record in records) == 2


@pytest.mark.asyncio
async def test_revised_closed_candle_appends_superseding_event(tmp_path: Path) -> None:
    responses = [_rows(), _rows(revised_close="60101.50")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=responses.pop(0), request=request)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = LiveBtc60Collector(
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        await collector.poll_once()
        first_records = list(store.iter_records())
        first_last_sequence = int(str(first_records[-1]["sequence"]))
        second = await collector.poll_once()

    assert second.revised_candle_count == 1
    candles = [record for record in store.iter_records() if record["event_type"] == "btc_candle"]
    target = [
        record
        for record in candles
        if isinstance(record["payload"], dict) and record["payload"]["open_epoch"] == 1786795260
    ]
    assert len(target) == 2
    assert target[1]["supersedes_event_id"] == target[0]["event_id"]
    revised_payload = target[1]["payload"]
    assert isinstance(revised_payload, dict)
    assert revised_payload["close"] == "60101.50"
    before_revision = load_latest_btc_candles(store, as_of_sequence=first_last_sequence)
    after_revision = load_latest_btc_candles(store)
    assert before_revision[0].close != after_revision[0].close
    assert after_revision[0].close == Decimal("60101.50")


@pytest.mark.asyncio
async def test_http_error_body_is_durable_before_failure(tmp_path: Path) -> None:
    raw = b'{"message":"busy"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=raw, request=request)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = LiveBtc60Collector(
            run_id="run-live",
            store=store,
            client=client,
            clock=_Clock(),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await collector.poll_once()

    records = list(store.iter_records())
    assert [record["event_type"] for record in records] == [
        "raw_observation",
        "source_health",
    ]
    payload = records[0]["payload"]
    assert isinstance(payload, dict)
    raw_path = tmp_path / str(payload["raw_body_path"])
    assert raw_path.read_bytes() == raw
