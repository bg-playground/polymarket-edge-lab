from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from polymarket_edge_lab.shadow.market_metadata import (
    LiveMarketMetadataResolver,
    classify_gamma_market,
)
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

CONDITION_ID = "0x" + "1" * 64
START = 1_786_795_200


def _market(
    *,
    slug: str = f"btc-updown-5m-{START}",
    outcomes: object = '["Up","Down"]',
    tokens: object = '["token-up","token-down"]',
) -> dict[str, object]:
    return {
        "id": "12345",
        "conditionId": CONDITION_ID,
        "slug": slug,
        "question": "Bitcoin Up or Down",
        "outcomes": outcomes,
        "clobTokenIds": tokens,
        "active": True,
        "closed": False,
        "acceptingOrders": True,
    }


def test_classification_preserves_stage3g_slug_start_and_maps_tokens() -> None:
    result = classify_gamma_market(_market(), response_sha256="a" * 64)
    assert result.eligible is True
    assert result.reason_code == "eligible"
    assert result.metadata is not None
    assert result.metadata.market_start_epoch == START
    assert result.metadata.market_end_epoch == START + 300
    assert result.metadata.up_token_id == "token-up"
    assert result.metadata.down_token_id == "token-down"
    assert result.metadata.outcome_side_for_token("token-up") == "UP"
    assert result.metadata.outcome_side_for_token("token-down") == "DOWN"
    assert result.metadata.outcome_side_for_token("other") is None


def test_outcome_order_controls_token_mapping() -> None:
    result = classify_gamma_market(
        _market(outcomes=["Down", "Up"], tokens=["token-down", "token-up"]),
        response_sha256="b" * 64,
    )
    assert result.metadata is not None
    assert result.metadata.up_token_id == "token-up"
    assert result.metadata.down_token_id == "token-down"


def test_non_stage3g_slug_fails_closed() -> None:
    result = classify_gamma_market(
        _market(slug="bitcoin-up-or-down"), response_sha256="c" * 64
    )
    assert result.eligible is False
    assert result.reason_code == "not_stage3g_btc_5m_slug"


def test_ambiguous_outcomes_fail_closed() -> None:
    result = classify_gamma_market(
        _market(outcomes='["Yes","No"]'), response_sha256="d" * 64
    )
    assert result.eligible is False
    assert result.reason_code == "outcomes_not_unambiguous_up_down"


@pytest.mark.asyncio
async def test_resolver_persists_raw_metadata_and_caches_result(tmp_path: Path) -> None:
    raw = json.dumps([_market()], separators=(",", ":")).encode()
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.params["condition_ids"] == CONDITION_ID
        return httpx.Response(200, content=raw, request=request)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resolver = LiveMarketMetadataResolver(run_id="run-1", store=store, client=client)
        first = await resolver.resolve(CONDITION_ID)
        second = await resolver.resolve(CONDITION_ID)
        restarted = LiveMarketMetadataResolver(run_id="run-1", store=store, client=client)
        third = await restarted.resolve(CONDITION_ID)

    assert first == second == third
    assert requests == 1
    records = list(store.iter_records())
    assert [record["event_type"] for record in records] == [
        "raw_observation",
        "market_metadata",
    ]
    raw_payload = records[0]["payload"]
    assert isinstance(raw_payload, dict)
    raw_path = tmp_path / str(raw_payload["raw_body_path"])
    assert raw_path.read_bytes() == raw
    metadata_payload = records[1]["payload"]
    assert isinstance(metadata_payload, dict)
    assert metadata_payload["eligible"] is True
    metadata = metadata_payload["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["up_token_id"] == "token-up"
    assert metadata["down_token_id"] == "token-down"


@pytest.mark.asyncio
async def test_condition_lookup_must_be_unique(tmp_path: Path) -> None:
    raw = b"[]"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, request=request)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resolver = LiveMarketMetadataResolver(run_id="run-1", store=store, client=client)
        result = await resolver.resolve(CONDITION_ID)

    assert result.eligible is False
    assert result.reason_code == "condition_lookup_not_unique"
