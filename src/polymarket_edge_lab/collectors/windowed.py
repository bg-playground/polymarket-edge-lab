"""Windowed pagination for complete Polymarket trade history.

The public Data API has a documented offset ceiling of 10 000 per query.
For high-volume accounts (e.g. nagi777) the total trade count may far exceed
this limit.  The API supports ``startTs`` / ``endTs`` epoch-second parameters
that narrow a query to a specific time window.  By iterating over
non-overlapping windows, each small enough to contain fewer than 10 000 trades,
the full history is obtainable.

Strategy
--------
1. Divide the collection period ``[global_start, global_end)`` into fixed-size
   windows (default: 30 days).
2. Paginate each window to exhaustion (offset/limit within the window).
3. If any window still hits the offset ceiling (meaning its trade count exceeds
   the limit), record it as ``ceiling_hit`` so it can be subdivided by the
   caller (e.g. by halving the window size and re-running).
4. All results are de-duplicated by ``source_trade_id`` across window boundaries.

Time parameters
---------------
The API's ``startTs``/``endTs`` parameters are documented as epoch **seconds**.
The response ``timestamp`` field is assumed to be epoch **milliseconds** (see
``normalization/trades.py`` and the plausibility guard therein).

TODO: Confirm parameter names (``startTs``/``endTs`` vs ``start``/``end``) and
      the response timestamp unit against a live response.

Resumability
------------
Each fetched page is saved to the raw manifest with ``(window_start,
window_end, offset)`` provenance.  On resume, already-saved
``(window_start, window_end, offset)`` triplets are skipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from polymarket_edge_lab.collectors.polymarket import OFFSET_CEILING, PolymarketPublicTradeCollector
from polymarket_edge_lab.normalization.trades import NormalizationResult, normalize_records
from polymarket_edge_lab.storage.raw import completed_window_offsets, write_raw_page

try:
    from pathlib import Path
except ImportError:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

# Default window size: 30 days expressed as seconds.
DEFAULT_WINDOW_SECONDS = 30 * 24 * 3600


@dataclass
class WindowResult:
    """Result of paginating a single time window."""

    window_start: int  # epoch seconds
    window_end: int  # epoch seconds
    normalization_results: list[NormalizationResult] = field(default_factory=list)
    ceiling_hit: bool = False  # True if this window reached OFFSET_CEILING

    @property
    def total_accepted(self) -> int:
        return sum(len(r.accepted) for r in self.normalization_results)

    @property
    def total_rejected(self) -> int:
        return sum(len(r.rejected) for r in self.normalization_results)

    @property
    def total_duplicates(self) -> int:
        return sum(len(r.duplicate_ids) for r in self.normalization_results)


def generate_windows(
    global_start: int,
    global_end: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> list[tuple[int, int]]:
    """Return a list of non-overlapping ``(start, end)`` epoch-second pairs.

    Windows span ``[global_start, global_end)`` in order from oldest to newest.
    The last window may be shorter than ``window_seconds``.

    Parameters
    ----------
    global_start:
        Inclusive lower bound (epoch seconds).
    global_end:
        Exclusive upper bound (epoch seconds).
    window_seconds:
        Size of each window in seconds (default: 30 days).
    """
    if global_start >= global_end:
        return []
    windows: list[tuple[int, int]] = []
    cur = global_start
    while cur < global_end:
        end = min(cur + window_seconds, global_end)
        windows.append((cur, end))
        cur = end
    return windows


async def collect_window(
    collector: PolymarketPublicTradeCollector,
    *,
    account: str,
    window_start: int,
    window_end: int,
    page_size: int = 100,
    raw_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> WindowResult:
    """Paginate a single time window to exhaustion, return a :class:`WindowResult`.

    Parameters
    ----------
    collector:
        Configured :class:`~collectors.polymarket.PolymarketPublicTradeCollector`.
    account:
        Proxy wallet address.
    window_start:
        Window lower bound (epoch seconds, inclusive).
    window_end:
        Window upper bound (epoch seconds, exclusive).
    page_size:
        Records per API page.
    raw_dir:
        If provided, raw pages are written here.
    force:
        Re-fetch pages even if the manifest says they are done.
    dry_run:
        Fetch and normalize but do not write to storage.

    Returns
    -------
    WindowResult
        ``ceiling_hit`` is True if the window still reached OFFSET_CEILING,
        meaning it should be subdivided.
    """
    result = WindowResult(window_start=window_start, window_end=window_end)

    # Load already-saved (window_start, window_end) → offset set for resume.
    done_by_window: dict[tuple[int, int], set[int]] = {}
    if raw_dir is not None and not force:
        done_by_window = completed_window_offsets(raw_dir, account)
    done_offsets = done_by_window.get((window_start, window_end), set())

    offset = 0
    while True:
        if offset >= OFFSET_CEILING:
            logger.warning(
                "Window [%d, %d): offset ceiling %d hit at offset %d — "
                "consider subdividing this window.",
                window_start,
                window_end,
                OFFSET_CEILING,
                offset,
            )
            result.ceiling_hit = True
            break

        if offset in done_offsets:
            logger.debug(
                "Window [%d, %d): skipping offset=%d (already saved)",
                window_start,
                window_end,
                offset,
            )
            offset += page_size
            continue

        logger.info(
            "Window [%d, %d): fetching offset=%d limit=%d",
            window_start,
            window_end,
            offset,
            page_size,
        )
        raw_bytes, records = await collector.fetch_page(
            account=account,
            offset=offset,
            limit=page_size,
            window_start=window_start,
            window_end=window_end,
        )
        page_count = len(records)

        endpoint_url = collector.endpoint_url(
            account=account,
            offset=offset,
            limit=page_size,
            window_start=window_start,
            window_end=window_end,
        )

        raw_path: Path | str = f"(dry-run-win-{window_start}-{window_end}-off-{offset})"
        content_hash = ""
        if not dry_run and raw_dir is not None:
            raw_path, content_hash = write_raw_page(
                raw_bytes,
                output_dir=raw_dir,
                account=account,
                offset=offset,
                limit=page_size,
                endpoint_url=endpoint_url,
                window_start=window_start,
                window_end=window_end,
            )

        norm = normalize_records(
            records,
            account=account,
            raw_page_path=str(raw_path),
            raw_page_hash=content_hash,
            offset=offset,
        )
        result.normalization_results.append(norm)

        if page_count < page_size:
            logger.info(
                "Window [%d, %d): short page (%d < %d) — end of window.",
                window_start,
                window_end,
                page_count,
                page_size,
            )
            break

        offset += page_size

    return result


async def collect_windowed(
    collector: PolymarketPublicTradeCollector,
    *,
    account: str,
    global_start: int,
    global_end: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    page_size: int = 100,
    raw_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[WindowResult]:
    """Collect complete trade history over ``[global_start, global_end)`` using windows.

    Iterates non-overlapping time windows of ``window_seconds`` size from
    oldest to newest.  Each window is paginated independently.  Returns one
    :class:`WindowResult` per window.

    Cross-window duplicate records are not de-duplicated here; the DuckDB
    upsert (``PRIMARY KEY`` skip) and the global normalization dedup set handle
    them at storage time.

    Parameters
    ----------
    global_start:
        Start of the collection period (epoch seconds).
    global_end:
        End of the collection period (epoch seconds, exclusive).  Pass
        ``int(datetime.now(UTC).timestamp())`` for "up to now".
    window_seconds:
        Size of each time window in seconds (default: 30 days = 2 592 000 s).
        Reduce this if any window still hits the offset ceiling.
    """
    windows = generate_windows(global_start, global_end, window_seconds=window_seconds)
    logger.info(
        "Windowed collection: %d windows of %ds each over [%d, %d)",
        len(windows),
        window_seconds,
        global_start,
        global_end,
    )
    results: list[WindowResult] = []
    for ws, we in windows:
        wr = await collect_window(
            collector,
            account=account,
            window_start=ws,
            window_end=we,
            page_size=page_size,
            raw_dir=raw_dir,
            force=force,
            dry_run=dry_run,
        )
        results.append(wr)
        if wr.ceiling_hit:
            logger.warning(
                "Window [%d, %d) hit the offset ceiling. "
                "Re-run with a smaller --window-seconds to retrieve all records.",
                ws,
                we,
            )
    return results


def deduplicate_across_windows(window_results: list[WindowResult]) -> list[Any]:
    """Return accepted trades de-duplicated by ``source_trade_id`` across windows.

    The API may return the same trade in adjacent windows when a trade's
    timestamp falls exactly on a window boundary.  This function ensures each
    ``source_trade_id`` appears at most once in the final output.
    """
    from polymarket_edge_lab.models.trade import NormalizedTrade

    seen: set[str] = set()
    out: list[NormalizedTrade] = []
    for wr in window_results:
        for norm in wr.normalization_results:
            for trade in norm.accepted:
                if trade.source_trade_id not in seen:
                    seen.add(trade.source_trade_id)
                    out.append(trade)
    return out
