#!/usr/bin/env python3
"""CLI: collect historical public trades for a Polymarket account.

Usage
-----
    python scripts/collect_historical_trades.py --account <PROXY_WALLET_ADDRESS>

Options
-------
    --account           Proxy wallet address to collect trades for (required).
    --page-size         Records per API page (default: 100, max: 500).
    --max-pages         Stop after this many pages (default: unlimited; non-windowed only).
    --limit             Stop after this many total records (default: unlimited; non-windowed).
    --raw-dir           Directory for raw JSON pages (default: data/raw).
    --normalized-dir    Directory for Parquet files (default: data/normalized).
    --duckdb-path       Path to DuckDB file (default: data/polymarket_edge_lab.duckdb).
    --force             Re-fetch pages even if the manifest says they are done.
    --base-url          Override the Data API base URL.
    --dry-run           Fetch and normalize but do not write to storage.
    --windowed          Use time-window pagination to bypass the 10 000 offset ceiling.
    --global-start      Start of collection period in epoch seconds (windowed mode).
    --global-end        End of collection period in epoch seconds (windowed; default: now).
    --window-seconds    Window size in seconds (windowed mode; default: 2592000 = 30 days).

First run for nagi777
---------------------
First obtain the proxy wallet address for nagi777 from the Polymarket UI:
  1. Visit https://polymarket.com/profile/nagi777
  2. The URL or profile page shows the proxy wallet (0x…) address.
  3. Pass it with --account.

Example (small public sample, no time window):
    python scripts/collect_historical_trades.py --account 0xYOUR_ADDR --max-pages 1

Example (windowed deep-history collection — bypasses 10 000 ceiling):
    python scripts/collect_historical_trades.py \\
        --account 0xSEE_README_FOR_VERIFIED_ADDRESS \\
        --windowed \\
        --global-start 1569888000 \\
        --window-seconds 2592000 \\
        --page-size 500

Notes
-----
* Without --windowed, the API has a documented offset ceiling of 10 000.
  The collector reports this boundary clearly.
* With --windowed, collection spans non-overlapping time windows.  Any window
  that still hits the ceiling is logged and flagged; re-run with a smaller
  --window-seconds to retrieve all records in that window.
* Raw pages are written as exact response bytes and are never overwritten.
* Runs are resumable: saved (window, offset) pairs are skipped on re-run unless
  --force is supplied.
* Non-zero exit code on fatal API/schema/storage errors.
* Rejected individual records are logged and counted but do not abort the run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure the src layout is importable when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from polymarket_edge_lab.collectors.polymarket import (
    OFFSET_CEILING,
    PolymarketPublicTradeCollector,
)
from polymarket_edge_lab.collectors.windowed import (
    DEFAULT_WINDOW_SECONDS,
    collect_windowed,
    deduplicate_across_windows,
)
from polymarket_edge_lab.normalization.trades import normalize_records
from polymarket_edge_lab.storage.normalized import write_duckdb, write_parquet
from polymarket_edge_lab.storage.raw import completed_offsets, write_raw_page
from polymarket_edge_lab.validation.completeness import summarize_window_completeness
from polymarket_edge_lab.validation.report import build_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("collect_historical_trades")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Collect public Polymarket trade history for an account."
    )
    p.add_argument("--account", required=True, help="Proxy wallet address (0x…)")
    p.add_argument("--page-size", type=int, default=100, help="Records per API page (max 500)")
    p.add_argument(
        "--max-pages", type=int, default=None, help="Stop after N pages (non-windowed only)"
    )
    p.add_argument(
        "--limit", type=int, default=None, help="Stop after N total records (non-windowed only)"
    )
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"), help="Raw output dir")
    p.add_argument(
        "--normalized-dir", type=Path, default=Path("data/normalized"), help="Parquet output dir"
    )
    p.add_argument(
        "--duckdb-path",
        type=Path,
        default=Path("data/polymarket_edge_lab.duckdb"),
        help="DuckDB file path",
    )
    p.add_argument("--force", action="store_true", help="Re-fetch already-saved pages")
    p.add_argument(
        "--base-url",
        default="https://data-api.polymarket.com",
        help="Override Data API base URL",
    )
    p.add_argument("--dry-run", action="store_true", help="Do not write to storage")
    # Windowed collection arguments.
    p.add_argument(
        "--windowed",
        action="store_true",
        help="Use time-window pagination to bypass the 10 000 offset ceiling.",
    )
    p.add_argument(
        "--global-start",
        type=int,
        default=None,
        help="Start of collection period (epoch seconds). Required with --windowed.",
    )
    p.add_argument(
        "--global-end",
        type=int,
        default=None,
        help="End of collection period (epoch seconds). Defaults to now.",
    )
    p.add_argument(
        "--window-seconds",
        type=int,
        default=DEFAULT_WINDOW_SECONDS,
        help=f"Window size in seconds (default: {DEFAULT_WINDOW_SECONDS} = 30 days).",
    )
    p.add_argument(
        "--min-window-seconds",
        type=int,
        default=3600,
        help="Minimum window size for automatic subdivision when ceiling is hit.",
    )
    return p.parse_args(argv)


async def run_windowed(args: argparse.Namespace) -> int:
    """Windowed collection mode: bypass offset ceiling with time-bounded windows."""
    if args.global_start is None:
        logger.error("--global-start is required with --windowed")
        return 1

    global_end: int = args.global_end or int(datetime.now(UTC).timestamp())
    global_start: int = args.global_start

    collector = PolymarketPublicTradeCollector(base_url=args.base_url, timeout_seconds=30.0)
    raw_dir: Path = args.raw_dir
    normalized_dir: Path = args.normalized_dir
    duckdb_path: Path = args.duckdb_path
    account: str = args.account
    page_size: int = min(args.page_size, 500)
    dry_run: bool = args.dry_run
    force: bool = args.force
    window_seconds: int = args.window_seconds

    logger.info(
        "Windowed mode: account=%s global_start=%d global_end=%d window_seconds=%d",
        account,
        global_start,
        global_end,
        window_seconds,
    )

    try:
        window_results = await collect_windowed(
            collector,
            account=account,
            global_start=global_start,
            global_end=global_end,
            window_seconds=window_seconds,
            page_size=page_size,
            raw_dir=raw_dir if not dry_run else None,
            force=force,
            dry_run=dry_run,
            min_window_seconds=args.min_window_seconds,
        )
    except Exception as exc:
        logger.error("Fatal error during windowed collection: %s", exc)
        return 1

    ceiling_windows = [wr for wr in window_results if wr.ceiling_hit]
    if ceiling_windows:
        logger.warning(
            "%d window(s) hit the offset ceiling. Re-run with a smaller "
            "--window-seconds to retrieve all records in those windows.",
            len(ceiling_windows),
        )

    all_accepted = deduplicate_across_windows(window_results)
    all_rejected = [
        r for wr in window_results for nr in wr.normalization_results for r in nr.rejected
    ]
    all_duplicate_ids = [
        d for wr in window_results for nr in wr.normalization_results for d in nr.duplicate_ids
    ]
    total_raw = sum(
        len(nr.accepted) + len(nr.rejected) + len(nr.duplicate_ids)
        for wr in window_results
        for nr in wr.normalization_results
    )

    if not dry_run and all_accepted:
        try:
            pq_path = write_parquet(all_accepted, normalized_dir, account)
            logger.info("Parquet written: %s", pq_path)
            inserted, skipped_dup = write_duckdb(all_accepted, duckdb_path)
            logger.info("DuckDB: inserted=%d skipped=%d", inserted, skipped_dup)
        except Exception as exc:
            logger.error("Storage error: %s", exc)
            return 1
    elif dry_run:
        logger.info("Dry run: skipping storage writes.")

    timestamps = [t.timestamp for t in all_accepted]
    report = build_report(
        input_records=total_raw,
        valid_records=len(all_accepted),
        duplicate_records=len(all_duplicate_ids),
        invalid_records=len(all_rejected),
        missing_required_fields=sum(
            1 for r in all_rejected if "missing required fields" in r.reason
        ),
        timestamps=timestamps,
    )
    print(report.summary())

    completeness = summarize_window_completeness(window_results)
    print(
        "\n=== Window Completeness ===\n"
        f"  Windows attempted     : {completeness.windows_attempted}\n"
        f"  Windows complete      : {completeness.windows_complete}\n"
        f"  Windows unresolved    : {completeness.windows_unresolved}\n"
        f"  Complete history gate : {completeness.complete}"
    )
    if completeness.unresolved_windows:
        print("  Unresolved windows:")
        for ws, we in completeness.unresolved_windows:
            print(f"    - [{ws}, {we})")

    if ceiling_windows:
        print(
            f"\nWARNING: {len(ceiling_windows)} window(s) hit the offset ceiling. "
            "Re-run with a smaller --window-seconds to retrieve all records."
        )

    if not completeness.complete:
        return 2
    return 0 if report.is_clean or len(all_accepted) > 0 else 1


async def run(args: argparse.Namespace) -> int:
    if args.windowed:
        return await run_windowed(args)

    collector = PolymarketPublicTradeCollector(base_url=args.base_url, timeout_seconds=30.0)

    raw_dir: Path = args.raw_dir
    normalized_dir: Path = args.normalized_dir
    duckdb_path: Path = args.duckdb_path
    account: str = args.account
    page_size: int = min(args.page_size, 500)
    max_pages: int | None = args.max_pages
    record_limit: int | None = args.limit
    force: bool = args.force
    dry_run: bool = args.dry_run

    already_done: set[int] = set()
    if not force:
        already_done = completed_offsets(raw_dir, account)
        if already_done:
            logger.info("Manifest: skipping %d already-saved offsets", len(already_done))

    all_accepted = []
    all_rejected = []
    all_duplicate_ids: list[str] = []
    total_raw = 0
    pages_fetched = 0
    offset = 0
    offset_ceiling_hit = False

    while True:
        if max_pages is not None and pages_fetched >= max_pages:
            logger.info("Reached --max-pages=%d, stopping.", max_pages)
            break
        if record_limit is not None and total_raw >= record_limit:
            logger.info("Reached --limit=%d, stopping.", record_limit)
            break

        if offset > OFFSET_CEILING:
            offset_ceiling_hit = True
            logger.warning(
                "Offset %d has reached the documented API ceiling of %d. "
                "Use --windowed to retrieve complete history beyond this bound.",
                offset,
                OFFSET_CEILING,
            )
            break

        if offset in already_done:
            logger.info(
                "Offset %d already in manifest, skipping (use --force to re-fetch).",
                offset,
            )
            offset += page_size
            continue

        try:
            logger.info("Fetching offset=%d limit=%d …", offset, page_size)
            raw_bytes, records = await collector.fetch_page(
                account=account, offset=offset, limit=page_size
            )
        except Exception as exc:
            logger.error("Fatal error fetching offset=%d: %s", offset, exc)
            return 1

        pages_fetched += 1
        page_count = len(records)
        total_raw += page_count

        endpoint_url = collector.endpoint_url(account=account, offset=offset, limit=page_size)

        if not dry_run:
            try:
                raw_path, content_hash = write_raw_page(
                    raw_bytes,
                    output_dir=raw_dir,
                    account=account,
                    offset=offset,
                    limit=page_size,
                    endpoint_url=endpoint_url,
                )
                logger.info("Saved raw page: %s (sha256:%s)", raw_path.name, content_hash[:12])
            except Exception as exc:
                logger.error("Failed to write raw page at offset=%d: %s", offset, exc)
                return 1
        else:
            raw_path = Path(f"(dry-run-offset-{offset})")
            content_hash = ""

        result = normalize_records(
            records,
            account=account,
            raw_page_path=str(raw_path),
            raw_page_hash=content_hash,
            offset=offset,
        )
        all_accepted.extend(result.accepted)
        all_rejected.extend(result.rejected)
        all_duplicate_ids.extend(result.duplicate_ids)

        if result.rejected:
            logger.warning("Page offset=%d: %d records rejected", offset, len(result.rejected))
            for r in result.rejected:
                logger.warning("  [%d] %s", r.index, r.reason)

        if page_count < page_size:
            logger.info("Short page (%d < %d): end of history.", page_count, page_size)
            break

        offset += page_size

    # Persist normalized data.
    if not dry_run and all_accepted:
        try:
            pq_path = write_parquet(all_accepted, normalized_dir, account)
            logger.info("Parquet written: %s", pq_path)
            inserted, skipped_dup = write_duckdb(all_accepted, duckdb_path)
            logger.info("DuckDB: inserted=%d skipped=%d", inserted, skipped_dup)
        except Exception as exc:
            logger.error("Storage error: %s", exc)
            return 1
    elif dry_run:
        logger.info("Dry run: skipping storage writes.")

    # Build and print validation report.
    timestamps = [t.timestamp for t in all_accepted]
    report = build_report(
        input_records=total_raw,
        valid_records=len(all_accepted),
        duplicate_records=len(all_duplicate_ids),
        invalid_records=len(all_rejected),
        missing_required_fields=sum(
            1 for r in all_rejected if "missing required fields" in r.reason
        ),
        timestamps=timestamps,
    )
    print(report.summary())

    if offset_ceiling_hit:
        print(
            "\nWARNING: API offset ceiling reached. Use --windowed to retrieve complete "
            f"trade history beyond offset {OFFSET_CEILING}."
        )

    return 0 if report.is_clean or len(all_accepted) > 0 else 1


def main() -> None:
    args = parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
