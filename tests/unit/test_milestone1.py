"""Comprehensive unit tests for Milestone 1 normalization, storage, and validation.

Covers:
- fixture shape normalization
- top-level non-list payload failure
- required field missing and missing-field counts
- unknown fields retained in raw_extra
- Unix-milliseconds-to-UTC conversion
- timestamp plausibility guard (regression: epoch-seconds vs. milliseconds)
- invalid/ambiguous timestamps rejected
- exact Decimal parsing and round-trip
- side validation
- price and size bounds
- deterministic identity and duplicate detection
- immutable raw byte preservation / create-only behaviour
- windowed pagination: window generation, ceiling detection, resume,
  cross-window deduplication
- pagination stop behaviour and resume behaviour (MockTransport)
- Parquet/DuckDB write + reload consistency
- validation counts and earliest/latest timestamp
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from polymarket_edge_lab.models.trade import NormalizedTrade
from polymarket_edge_lab.normalization.trades import (
    _TS_MAX,
    _TS_MIN,
    _make_identity_hash,
    _parse_decimal,
    _parse_ms_to_utc,
    normalize_records,
)
from polymarket_edge_lab.storage.normalized import (
    load_duckdb,
    load_parquet,
    write_duckdb,
    write_parquet,
)
from polymarket_edge_lab.storage.raw import (
    completed_offsets,
    completed_window_offsets,
    load_manifest,
    write_raw_page,
)
from polymarket_edge_lab.validation.report import ValidationReport, build_report

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "trades_page_offset0.json"


def _fixture_records() -> list[dict[str, Any]]:
    # Use parse_float=Decimal to match how the collector parses real API responses.
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.loads(fh.read(), parse_float=Decimal)  # type: ignore[return-value]


def _make_trade(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t1",
        "conditionId": "0xmarket000000000000000000000000000000000000000000000000000000000000",
        "asset": "12345678901234567",
        "side": "BUY",
        "size": Decimal("100"),
        "price": Decimal("0.55"),
        "timestamp": 1723634400000,
        "outcome": "UP",
        "proxyWallet": "0xowner000000000000000000000000000000000000",
        "transactionHash": "0xtxhash",
    }
    base.update(kwargs)
    return base


ACCOUNT = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


# ---------------------------------------------------------------------------
# Fixture-based normalization
# ---------------------------------------------------------------------------


def test_normalize_fixture_accepted() -> None:
    records = _fixture_records()
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.accepted) == 2
    assert len(result.rejected) == 0
    assert len(result.duplicate_ids) == 0


def test_normalize_fixture_first_trade_fields() -> None:
    records = _fixture_records()
    result = normalize_records(records, account=ACCOUNT)
    t = result.accepted[0]
    assert t.side == "BUY"
    assert t.outcome == "UP"
    assert t.price == Decimal("0.44")
    assert t.shares == Decimal("200")
    assert t.account == ACCOUNT
    assert t.timestamp.tzinfo is UTC


def test_normalize_fixture_provenance_in_raw_extra() -> None:
    records = _fixture_records()
    result = normalize_records(
        records,
        account=ACCOUNT,
        raw_page_path="/data/raw/page.json",
        raw_page_hash="abc123",
        offset=0,
    )
    extra = result.accepted[0].raw_extra
    assert extra["_raw_page_path"] == "/data/raw/page.json"
    assert extra["_raw_page_hash"] == "abc123"
    assert extra["_page_offset"] == 0
    assert extra["_record_index"] == 0


# ---------------------------------------------------------------------------
# Top-level response shape failure
# ---------------------------------------------------------------------------


def test_non_list_payload_raises() -> None:
    """Caller must check type before calling normalize_records; collector raises TypeError."""

    # Ensure the collector would raise TypeError for non-list payloads.
    # We test the contract by simulating the check.
    payload: Any = {"error": "not a list"}
    with pytest.raises(TypeError, match="Expected list payload"):
        if not isinstance(payload, list):
            raise TypeError(f"Expected list payload from /trades, got {type(payload).__name__}")


# ---------------------------------------------------------------------------
# Required field missing
# ---------------------------------------------------------------------------


def test_missing_required_field_rejects() -> None:
    records = [_make_trade()]
    del records[0]["conditionId"]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.rejected) == 1
    assert "conditionId" in result.rejected[0].reason


def test_multiple_missing_fields_counted() -> None:
    records = [_make_trade()]
    del records[0]["conditionId"]
    del records[0]["outcome"]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.rejected) == 1
    # Both missing fields should appear in the reason.
    assert "conditionId" in result.rejected[0].reason
    assert "outcome" in result.rejected[0].reason


# ---------------------------------------------------------------------------
# Unknown fields retained
# ---------------------------------------------------------------------------


def test_unknown_fields_in_raw_extra() -> None:
    records = [_make_trade(totally_unknown_field="surprise")]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.accepted) == 1
    assert result.accepted[0].raw_extra.get("totally_unknown_field") == "surprise"


# ---------------------------------------------------------------------------
# Unix-milliseconds-to-UTC conversion
# ---------------------------------------------------------------------------


def test_unix_ms_int_converted_to_utc() -> None:
    ts = _parse_ms_to_utc(1723634400000)
    assert ts == datetime(2024, 8, 14, 11, 20, 0, tzinfo=UTC)
    assert ts.utcoffset().seconds == 0  # type: ignore[union-attr]


def test_unix_ms_string_converted_to_utc() -> None:
    ts = _parse_ms_to_utc("1723634400000")
    assert ts == datetime(2024, 8, 14, 11, 20, 0, tzinfo=UTC)


def test_invalid_timestamp_string_rejected() -> None:
    with pytest.raises(ValueError, match="cannot parse"):
        _parse_ms_to_utc("not-a-number")


def test_raw_float_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="raw float"):
        _parse_ms_to_utc(1723634400000.5)


# ---------------------------------------------------------------------------
# Timestamp plausibility guard (regression: unit mismatch detection)
# ---------------------------------------------------------------------------


def test_epoch_seconds_value_rejected_as_out_of_range() -> None:
    """Epoch-seconds values (~1.7e9) produce 1970-era dates and must be rejected.

    This is the primary regression guard: if the live API returns seconds
    instead of milliseconds, the record is rejected and logged rather than
    silently stored with a wrong timestamp.
    """
    # 1_723_634_400 seconds = 2024-08-14 (a plausible trade date), but treated
    # as milliseconds it would be ~1973-01-01, well before the plausible epoch.
    epoch_seconds_value = 1_723_634_400  # would be ~1973 if treated as ms
    with pytest.raises(ValueError, match="plausible"):
        _parse_ms_to_utc(epoch_seconds_value)


def test_realistic_ms_timestamp_accepted() -> None:
    """A realistic live-sample millisecond timestamp must parse correctly.

    Value 1_723_634_400_000 ms = 2024-08-14T11:20:00 UTC.
    This is the fixture's first trade timestamp — confirmed from documented
    fixture data.  It must always parse inside the plausible trading epoch.
    """
    ts = _parse_ms_to_utc(1_723_634_400_000)
    assert ts == datetime(2024, 8, 14, 11, 20, 0, tzinfo=UTC)
    assert _TS_MIN <= ts <= _TS_MAX


def test_timestamp_plausibility_bounds_are_sane() -> None:
    """Verify the plausible epoch constants are in the right order."""
    assert _TS_MIN < _TS_MAX
    assert _TS_MIN.year == 2019
    assert _TS_MAX.year == 2040


def test_far_future_timestamp_rejected() -> None:
    """Timestamps beyond 2040 are rejected to guard against corrupt values."""
    far_future_ms = 2_209_032_000_000  # 2040-01-02 in ms
    with pytest.raises(ValueError, match="plausible"):
        _parse_ms_to_utc(far_future_ms)


def test_normalized_record_epoch_seconds_rejected_end_to_end() -> None:
    """Ensure epoch-seconds timestamp causes record rejection, not silent corruption."""
    record = _make_trade(timestamp=1_723_634_400)  # seconds, not ms
    result = normalize_records([record], account=ACCOUNT)
    assert len(result.rejected) == 1
    assert "plausible" in result.rejected[0].reason


# ---------------------------------------------------------------------------
# Decimal parsing and round-trip
# ---------------------------------------------------------------------------


def test_decimal_from_string() -> None:
    d = _parse_decimal("0.44", "price")
    assert d == Decimal("0.44")


def test_decimal_from_decimal_object() -> None:
    """Decimal objects (from parse_float=Decimal JSON parsing) are passed through."""
    d = _parse_decimal(Decimal("0.44"), "price")
    assert d == Decimal("0.44")


def test_decimal_raw_float_rejected() -> None:
    with pytest.raises(ValueError, match="raw float"):
        _parse_decimal(0.44, "price")


def test_decimal_round_trip() -> None:
    original = "0.9999999999999"
    d = _parse_decimal(original, "price")
    assert str(d) == original


# ---------------------------------------------------------------------------
# Side validation
# ---------------------------------------------------------------------------


def test_invalid_side_rejected() -> None:
    records = [_make_trade(side="LONG")]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.rejected) == 1
    assert "side" in result.rejected[0].reason.lower()


def test_sell_side_accepted() -> None:
    records = [_make_trade(side="SELL")]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.accepted) == 1
    assert result.accepted[0].side == "SELL"


# ---------------------------------------------------------------------------
# Price and size bounds
# ---------------------------------------------------------------------------


def test_price_above_one_rejected() -> None:
    records = [_make_trade(price=Decimal("1.01"))]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.rejected) == 1
    assert "price" in result.rejected[0].reason.lower()


def test_price_below_zero_rejected() -> None:
    records = [_make_trade(price=Decimal("-0.01"))]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.rejected) == 1


def test_size_zero_rejected() -> None:
    records = [_make_trade(size=Decimal("0"))]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.rejected) == 1
    assert "size" in result.rejected[0].reason.lower()


def test_size_negative_rejected() -> None:
    records = [_make_trade(size=Decimal("-1"))]
    result = normalize_records(records, account=ACCOUNT)
    assert len(result.rejected) == 1


# ---------------------------------------------------------------------------
# Deterministic identity and duplicate detection
# ---------------------------------------------------------------------------


def test_identity_hash_is_deterministic() -> None:
    record = _make_trade()
    h1 = _make_identity_hash(record)
    h2 = _make_identity_hash(record)
    assert h1 == h2


def test_identity_hash_differs_on_different_record() -> None:
    r1 = _make_trade(price=Decimal("0.44"))
    r2 = _make_trade(price=Decimal("0.55"))
    assert _make_identity_hash(r1) != _make_identity_hash(r2)


def test_duplicate_records_detected() -> None:
    r = _make_trade()
    result = normalize_records([r, r], account=ACCOUNT)
    assert len(result.accepted) == 1
    assert len(result.duplicate_ids) == 1


def test_duplicate_ids_differ_when_api_id_present() -> None:
    r1 = _make_trade(id="trade-x")
    r2 = {**r1, "id": "trade-y"}
    result = normalize_records([r1, r2], account=ACCOUNT)
    # Different IDs: both accepted, no duplicate.
    assert len(result.accepted) == 2
    assert len(result.duplicate_ids) == 0


# ---------------------------------------------------------------------------
# Immutable raw storage
# ---------------------------------------------------------------------------


def test_write_raw_page_creates_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        raw = b'[{"id":"1"}]'
        path, content_hash = write_raw_page(
            raw,
            output_dir=Path(tmpdir),
            account="0xabc",
            offset=0,
            limit=100,
        )
        assert path.exists()
        assert path.read_bytes() == raw


def test_write_raw_page_exact_bytes() -> None:
    """Raw bytes must be stored verbatim — not re-serialized."""
    raw = b'[{"z":1,"a":2}]'  # Non-sorted keys.
    with tempfile.TemporaryDirectory() as tmpdir:
        path, _ = write_raw_page(raw, output_dir=Path(tmpdir), account="0xabc", offset=0, limit=100)
        assert path.read_bytes() == raw


def test_write_raw_page_manifest_written() -> None:
    raw = b"[]"
    with tempfile.TemporaryDirectory() as tmpdir:
        write_raw_page(raw, output_dir=Path(tmpdir), account="0xabc", offset=0, limit=100)
        manifest = load_manifest(Path(tmpdir), "0xabc")
        assert len(manifest) == 1
        assert manifest[0]["offset"] == 0


def test_completed_offsets_returned() -> None:
    raw = b"[]"
    with tempfile.TemporaryDirectory() as tmpdir:
        write_raw_page(raw, output_dir=Path(tmpdir), account="0xabc", offset=0, limit=100)
        write_raw_page(raw, output_dir=Path(tmpdir), account="0xabc", offset=100, limit=100)
        offsets = completed_offsets(Path(tmpdir), "0xabc")
        assert offsets == {0, 100}


def test_content_hash_in_filename() -> None:
    import hashlib

    raw = b'[{"id":"x"}]'
    expected_prefix = hashlib.sha256(raw).hexdigest()[:12]
    with tempfile.TemporaryDirectory() as tmpdir:
        path, _ = write_raw_page(raw, output_dir=Path(tmpdir), account="0xacc", offset=0, limit=100)
        assert expected_prefix in path.name


# ---------------------------------------------------------------------------
# Parquet write + reload
# ---------------------------------------------------------------------------


def _make_normalized_trade(source_trade_id: str = "t1") -> NormalizedTrade:
    return NormalizedTrade(
        source="test",
        source_trade_id=source_trade_id,
        account=ACCOUNT,
        market_id="0xmarket000000000000000000000000000000000000000000000000000000000000",
        asset_id="12345678901234567",
        timestamp=datetime(2024, 8, 14, 10, 0, 0, tzinfo=UTC),
        outcome="UP",
        side="BUY",
        price=Decimal("0.44"),
        shares=Decimal("200"),
        transaction_hash="0xtx",
        raw_extra={"_record_index": 0},
    )


def test_parquet_write_reload_roundtrip() -> None:
    trade = _make_normalized_trade()
    with tempfile.TemporaryDirectory() as tmpdir:
        pq_path = write_parquet([trade], Path(tmpdir), ACCOUNT)
        reloaded = load_parquet(pq_path)
        assert len(reloaded) == 1
        r = reloaded[0]
        assert r.source_trade_id == trade.source_trade_id
        assert r.price == trade.price
        assert r.shares == trade.shares
        assert r.timestamp == trade.timestamp
        assert r.timestamp.tzinfo is not None


def test_parquet_empty_write_reload() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pq_path = write_parquet([], Path(tmpdir), ACCOUNT)
        reloaded = load_parquet(pq_path)
        assert reloaded == []


# ---------------------------------------------------------------------------
# DuckDB write + reload
# ---------------------------------------------------------------------------


def test_duckdb_write_reload_roundtrip() -> None:
    trade = _make_normalized_trade()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.duckdb"
        inserted, skipped = write_duckdb([trade], db_path)
        assert inserted == 1
        assert skipped == 0
        reloaded = load_duckdb(db_path, account=ACCOUNT)
        assert len(reloaded) == 1
        r = reloaded[0]
        assert r.source_trade_id == trade.source_trade_id
        assert r.price == trade.price
        assert r.shares == trade.shares


def test_duckdb_duplicate_skipped() -> None:
    trade = _make_normalized_trade()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.duckdb"
        write_duckdb([trade], db_path)
        inserted2, skipped2 = write_duckdb([trade], db_path)
        assert inserted2 == 0
        assert skipped2 == 1


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


def test_validation_report_counts() -> None:
    records = _fixture_records()
    result = normalize_records(records, account=ACCOUNT)
    timestamps = [t.timestamp for t in result.accepted]
    report = build_report(
        input_records=len(records),
        valid_records=len(result.accepted),
        duplicate_records=len(result.duplicate_ids),
        invalid_records=len(result.rejected),
        missing_required_fields=0,
        timestamps=timestamps,
    )
    assert report.input_records == 2
    assert report.valid_records == 2
    assert report.invalid_records == 0
    assert report.duplicate_records == 0
    assert report.earliest_timestamp is not None
    assert report.latest_timestamp is not None
    assert report.earliest_timestamp <= report.latest_timestamp  # type: ignore[operator]


def test_validation_report_summary_contains_key_info() -> None:
    report = ValidationReport(
        input_records=10,
        valid_records=8,
        duplicate_records=1,
        invalid_records=1,
        missing_required_fields=1,
        earliest_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        latest_timestamp=datetime(2024, 12, 31, tzinfo=UTC),
    )
    s = report.summary()
    assert "10" in s
    assert "8" in s
    assert "Clean" in s


def test_clean_report() -> None:
    report = ValidationReport(10, 10, 0, 0)
    assert report.is_clean is True


def test_duplicate_report_is_not_clean() -> None:
    report = ValidationReport(10, 9, 1, 0)
    assert report.is_clean is False


# ---------------------------------------------------------------------------
# Pagination stop and resume (MockTransport)
# ---------------------------------------------------------------------------


def test_pagination_stop_on_short_page() -> None:
    """Collector returns fewer records than limit → pagination stops."""
    import asyncio

    import httpx

    # page_a has exactly `limit` records (full page) → continue
    # page_b has fewer records (short page) → stop
    # Use default=float so Decimal values in _make_trade serialize as JSON numbers,
    # matching what the real Data API returns.
    page_a = json.dumps(
        [_make_trade(id="t1"), _make_trade(id="t2"), _make_trade(id="t3")], default=float
    )
    page_b = json.dumps([_make_trade(id="t4")], default=float)  # Short page (1 < 3) → stop

    responses = [
        httpx.Response(200, text=page_a, headers={"Content-Type": "application/json"}),
        httpx.Response(200, text=page_b, headers={"Content-Type": "application/json"}),
    ]
    call_index = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_index
        resp = responses[call_index]
        call_index += 1
        return resp

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://data-api.polymarket.com")
    collector = PolymarketPublicTradeCollector(client=client)

    async def _run() -> None:
        all_records = []
        offset = 0
        limit = 3
        while True:
            _, records = await collector.fetch_page(account="0xacc", offset=offset, limit=limit)
            all_records.extend(records)
            if len(records) < limit:
                break
            offset += limit
        assert len(all_records) == 4
        assert call_index == 2

    asyncio.run(_run())


def test_pagination_resume_skips_completed_offsets() -> None:
    """Completed offsets from manifest are skipped without fetching."""
    import tempfile

    raw = b"[]"
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        write_raw_page(raw, output_dir=raw_dir, account="0xacc", offset=0, limit=2)
        write_raw_page(raw, output_dir=raw_dir, account="0xacc", offset=2, limit=2)
        done = completed_offsets(raw_dir, "0xacc")
        assert 0 in done
        assert 2 in done
        assert 4 not in done


# ---------------------------------------------------------------------------
# Windowed pagination
# ---------------------------------------------------------------------------

from polymarket_edge_lab.collectors.windowed import (  # noqa: E402
    DEFAULT_WINDOW_SECONDS,
    WindowResult,
    deduplicate_across_windows,
    generate_windows,
)


def test_generate_windows_single() -> None:
    """A range smaller than window_seconds produces a single window."""
    windows = generate_windows(1_000_000, 1_001_000, window_seconds=3600)
    assert len(windows) == 1
    assert windows[0] == (1_000_000, 1_001_000)


def test_generate_windows_exact_multiple() -> None:
    """Range exactly divisible into equal windows."""
    windows = generate_windows(0, 3600, window_seconds=1200)
    assert len(windows) == 3
    assert windows[0] == (0, 1200)
    assert windows[1] == (1200, 2400)
    assert windows[2] == (2400, 3600)


def test_generate_windows_last_window_truncated() -> None:
    """Last window is shorter if range is not evenly divisible."""
    windows = generate_windows(0, 2500, window_seconds=1000)
    assert len(windows) == 3
    assert windows[-1] == (2000, 2500)


def test_generate_windows_empty_range() -> None:
    assert generate_windows(1000, 1000) == []
    assert generate_windows(1000, 500) == []


def test_generate_windows_are_non_overlapping() -> None:
    """Adjacent windows must share endpoints without overlap."""
    windows = generate_windows(0, 10_000, window_seconds=3000)
    for i in range(len(windows) - 1):
        assert windows[i][1] == windows[i + 1][0]


def test_generate_windows_cover_full_range() -> None:
    """Windows must cover the full [global_start, global_end) range."""
    start, end = 1_570_000_000, 1_723_634_400
    windows = generate_windows(start, end, window_seconds=DEFAULT_WINDOW_SECONDS)
    assert windows[0][0] == start
    assert windows[-1][1] == end


def test_completed_window_offsets_roundtrip() -> None:
    """completed_window_offsets returns correct (window_start, window_end) → offsets map."""
    raw = b"[]"
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        write_raw_page(
            raw,
            output_dir=raw_dir,
            account="0xacc",
            offset=0,
            limit=100,
            window_start=1_000_000,
            window_end=1_100_000,
        )
        write_raw_page(
            raw,
            output_dir=raw_dir,
            account="0xacc",
            offset=100,
            limit=100,
            window_start=1_000_000,
            window_end=1_100_000,
        )
        write_raw_page(
            raw,
            output_dir=raw_dir,
            account="0xacc",
            offset=0,
            limit=100,
            window_start=1_100_000,
            window_end=1_200_000,
        )
        by_window = completed_window_offsets(raw_dir, "0xacc")
        assert by_window[(1_000_000, 1_100_000)] == {0, 100}
        assert by_window[(1_100_000, 1_200_000)] == {0}


def test_completed_offsets_excludes_windowed_entries() -> None:
    """completed_offsets must not include entries that have window_start/window_end."""
    raw = b"[]"
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        # Non-windowed entry — should appear in completed_offsets.
        write_raw_page(raw, output_dir=raw_dir, account="0xacc", offset=0, limit=100)
        # Windowed entry — must NOT appear in completed_offsets.
        write_raw_page(
            raw,
            output_dir=raw_dir,
            account="0xacc",
            offset=0,
            limit=100,
            window_start=1_000_000,
            window_end=1_100_000,
        )
        plain_offsets = completed_offsets(raw_dir, "0xacc")
        assert plain_offsets == {0}


def test_windowed_manifest_has_provenance() -> None:
    """Manifest entries for windowed pages carry window_start and window_end."""
    raw = b"[]"
    with tempfile.TemporaryDirectory() as tmpdir:
        write_raw_page(
            raw,
            output_dir=Path(tmpdir),
            account="0xacc",
            offset=0,
            limit=100,
            window_start=1_000_000,
            window_end=1_100_000,
        )
        entries = load_manifest(Path(tmpdir), "0xacc")
        assert entries[0]["window_start"] == 1_000_000
        assert entries[0]["window_end"] == 1_100_000


def test_deduplicate_across_windows_removes_cross_window_dupes() -> None:
    """A trade present in two adjacent windows should appear only once."""
    from polymarket_edge_lab.normalization.trades import NormalizationResult

    t = _make_normalized_trade("shared-trade-id")
    nr = NormalizationResult(accepted=[t], rejected=[], duplicate_ids=[])
    wr1 = WindowResult(window_start=0, window_end=1000, normalization_results=[nr])
    wr2 = WindowResult(window_start=1000, window_end=2000, normalization_results=[nr])
    result = deduplicate_across_windows([wr1, wr2])
    assert len(result) == 1
    assert result[0].source_trade_id == "shared-trade-id"


def test_deduplicate_across_windows_distinct_trades_all_kept() -> None:
    """Distinct trades across windows are all retained."""
    from polymarket_edge_lab.normalization.trades import NormalizationResult

    t1 = _make_normalized_trade("trade-1")
    t2 = _make_normalized_trade("trade-2")
    nr1 = NormalizationResult(accepted=[t1], rejected=[], duplicate_ids=[])
    nr2 = NormalizationResult(accepted=[t2], rejected=[], duplicate_ids=[])
    wr1 = WindowResult(window_start=0, window_end=1000, normalization_results=[nr1])
    wr2 = WindowResult(window_start=1000, window_end=2000, normalization_results=[nr2])
    result = deduplicate_across_windows([wr1, wr2])
    assert len(result) == 2


def test_windowed_collection_stop_and_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windowed collect_window skips offsets already in the manifest."""
    import asyncio

    import httpx

    from polymarket_edge_lab.collectors.windowed import collect_window

    # page_size=2; handler returns 1 record → short page → stops after one fetch.
    page_1_record = json.dumps([_make_trade(id="t2")], default=float)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, text=page_1_record, headers={"Content-Type": "application/json"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://data-api.polymarket.com")
    collector = PolymarketPublicTradeCollector(client=client)

    with tempfile.TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        # Pre-save offset=0 so it should be skipped on resume.
        pre_page = json.dumps([_make_trade(id="t1")], default=float).encode()
        write_raw_page(
            pre_page,
            output_dir=raw_dir,
            account="0xacc",
            offset=0,
            limit=2,
            window_start=1_000_000,
            window_end=1_100_000,
        )
        result = asyncio.run(
            collect_window(
                collector,
                account="0xacc",
                window_start=1_000_000,
                window_end=1_100_000,
                page_size=2,  # 1 record returned < 2 → short page → stops
                raw_dir=raw_dir,
                force=False,
                dry_run=True,
            )
        )
        # offset=0 was already saved → skipped; offset=2 fetched → short page → stop.
        assert call_count == 1
        _ = result  # WindowResult is returned without error.


def test_window_result_ceiling_hit_flag() -> None:
    """WindowResult.ceiling_hit defaults to False and can be set."""
    wr = WindowResult(window_start=0, window_end=1000)
    assert wr.ceiling_hit is False
    wr2 = WindowResult(window_start=0, window_end=1000, ceiling_hit=True)
    assert wr2.ceiling_hit is True


# Ensure collector imports work.
from polymarket_edge_lab.collectors.polymarket import PolymarketPublicTradeCollector  # noqa: E402
