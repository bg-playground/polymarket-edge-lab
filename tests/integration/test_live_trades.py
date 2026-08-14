"""Integration tests: explicitly opt-in via POLYMARKET_INTEGRATION_TESTS=1.

These tests call the live public Polymarket Data API and are skipped by
default.  Set the environment variable to run them:

    POLYMARKET_INTEGRATION_TESTS=1 pytest tests/integration/

The test fetches only 2 records (limit=2, offset=0) to minimize load.
No credentials or private keys are used.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

INTEGRATION_ENV = "POLYMARKET_INTEGRATION_TESTS"
skip_unless_integration = pytest.mark.skipif(
    os.environ.get(INTEGRATION_ENV) != "1",
    reason=f"Set {INTEGRATION_ENV}=1 to enable integration tests",
)

# A well-known public address with known trade activity (to be verified by the
# repository owner before first production run):
# nagi777 proxy wallet — obtain from https://polymarket.com/profile/nagi777
# Replace with the verified address before running.
TEST_ACCOUNT = os.environ.get("POLYMARKET_TEST_ACCOUNT", "")


@skip_unless_integration
def test_live_fetch_normalize_persist_reload() -> None:
    """End-to-end: fetch 2 records, save raw, normalize, persist, reload."""
    if not TEST_ACCOUNT:
        pytest.skip(
            "Set POLYMARKET_TEST_ACCOUNT=0x... to specify the account for integration tests"
        )

    from polymarket_edge_lab.collectors.polymarket import PolymarketPublicTradeCollector
    from polymarket_edge_lab.normalization.trades import normalize_records
    from polymarket_edge_lab.storage.normalized import load_duckdb, write_duckdb
    from polymarket_edge_lab.storage.raw import write_raw_page
    from polymarket_edge_lab.validation.report import build_report

    async def _run() -> None:
        collector = PolymarketPublicTradeCollector()
        raw_bytes, records = await collector.fetch_page(account=TEST_ACCOUNT, offset=0, limit=2)
        assert isinstance(records, list), "Expected list from API"

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir) / "raw"
            db_path = Path(tmpdir) / "test.duckdb"

            raw_path, content_hash = write_raw_page(
                raw_bytes,
                output_dir=raw_dir,
                account=TEST_ACCOUNT,
                offset=0,
                limit=2,
                endpoint_url=collector.endpoint_url(account=TEST_ACCOUNT, offset=0, limit=2),
            )
            assert raw_path.exists()
            assert raw_path.read_bytes() == raw_bytes, "Raw bytes must be stored verbatim"

            # Verify stored JSON is parseable and matches records.
            stored_records = json.loads(raw_path.read_bytes())
            assert stored_records == records

            result = normalize_records(
                records,
                account=TEST_ACCOUNT,
                raw_page_path=str(raw_path),
                raw_page_hash=content_hash,
                offset=0,
            )

            total = len(records)
            report = build_report(
                input_records=total,
                valid_records=len(result.accepted),
                duplicate_records=len(result.duplicate_ids),
                invalid_records=len(result.rejected),
                missing_required_fields=sum(
                    1 for r in result.rejected if "missing required fields" in r.reason
                ),
                timestamps=[t.timestamp for t in result.accepted],
            )
            print(report.summary())

            if result.accepted:
                inserted, skipped = write_duckdb(result.accepted, db_path)
                reloaded = load_duckdb(db_path, account=TEST_ACCOUNT)
                assert len(reloaded) == inserted
                # Price and shares round-trip without loss.
                assert reloaded[0].price == result.accepted[0].price
                assert reloaded[0].shares == result.accepted[0].shares

    asyncio.run(_run())
