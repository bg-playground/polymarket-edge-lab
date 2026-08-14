"""Normalized trade storage: Parquet and DuckDB backends.

Both backends are implemented. The DuckDB store keeps a persistent table;
the Parquet store writes one file per batch.  Both support upsert-style
duplicate detection: rows with an existing ``source_trade_id`` are skipped.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from polymarket_edge_lab.models.trade import NormalizedTrade

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Arrow schema
# ---------------------------------------------------------------------------

ARROW_SCHEMA = pa.schema(
    [
        pa.field("source", pa.string()),
        pa.field("source_trade_id", pa.string()),
        pa.field("account", pa.string()),
        pa.field("market_id", pa.string()),
        pa.field("asset_id", pa.string()),
        pa.field("timestamp", pa.timestamp("us", tz="UTC")),
        pa.field("outcome", pa.string()),
        pa.field("side", pa.string()),
        pa.field("price", pa.string()),  # stored as string to preserve Decimal precision
        pa.field("shares", pa.string()),  # stored as string to preserve Decimal precision
        pa.field("transaction_hash", pa.string()),
        pa.field("outcome_index", pa.int64()),
        pa.field("slug", pa.string()),
        pa.field("event_slug", pa.string()),
        pa.field("title", pa.string()),
        pa.field("raw_extra", pa.string()),  # JSON string
    ]
)


def _trade_to_row(trade: NormalizedTrade) -> dict[str, Any]:
    return {
        "source": trade.source,
        "source_trade_id": trade.source_trade_id,
        "account": trade.account,
        "market_id": trade.market_id,
        "asset_id": trade.asset_id,
        "timestamp": trade.timestamp,
        "outcome": trade.outcome,
        "side": trade.side,
        "price": str(trade.price),
        "shares": str(trade.shares),
        "transaction_hash": trade.transaction_hash or "",
        "outcome_index": trade.outcome_index,
        "slug": trade.slug or "",
        "event_slug": trade.event_slug or "",
        "title": trade.title or "",
        "raw_extra": json.dumps(trade.raw_extra),
    }


def _row_to_trade(row: dict[str, Any]) -> NormalizedTrade:
    # Ensure timestamp is tz-aware UTC datetime.
    ts = row["timestamp"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo is None:
        from datetime import UTC

        ts = ts.replace(tzinfo=UTC)

    raw_extra: dict[str, Any] = json.loads(row["raw_extra"]) if row["raw_extra"] else {}
    return NormalizedTrade(
        source=row["source"],
        source_trade_id=row["source_trade_id"],
        account=row["account"],
        market_id=row["market_id"],
        asset_id=row["asset_id"],
        timestamp=ts,
        outcome=row["outcome"],
        side=row["side"],
        price=Decimal(row["price"]),
        shares=Decimal(row["shares"]),
        transaction_hash=row["transaction_hash"] or None,
        outcome_index=row.get("outcome_index"),
        slug=row.get("slug") or None,
        event_slug=row.get("event_slug") or None,
        title=row.get("title") or None,
        raw_extra=raw_extra,
    )


# ---------------------------------------------------------------------------
# Parquet backend
# ---------------------------------------------------------------------------


def write_parquet(
    trades: list[NormalizedTrade],
    output_dir: Path,
    account: str,
    batch_label: str = "",
) -> Path:
    """Write trades to a Parquet file.

    Returns the path of the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    from datetime import UTC

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{batch_label}" if batch_label else ""
    path = output_dir / f"trades_{account}{suffix}_{stamp}.parquet"

    rows = [_trade_to_row(t) for t in trades]
    if not rows:
        table = pa.table(
            {f.name: pa.array([], type=f.type) for f in ARROW_SCHEMA},
            schema=ARROW_SCHEMA,
        )
    else:
        table = pa.Table.from_pylist(rows, schema=ARROW_SCHEMA)

    pq.write_table(table, path)
    logger.info("Wrote %d trades to %s", len(trades), path)
    return path


def load_parquet(path: Path) -> list[NormalizedTrade]:
    """Load trades from a Parquet file (no pandas required)."""
    table = pq.read_table(path, schema=ARROW_SCHEMA)
    results: list[NormalizedTrade] = []
    batch = table.to_pydict()
    n = table.num_rows
    for i in range(n):
        row = {col: batch[col][i] for col in batch}
        results.append(_row_to_trade(row))
    return results


# ---------------------------------------------------------------------------
# DuckDB backend
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    source VARCHAR NOT NULL,
    source_trade_id VARCHAR NOT NULL,
    account VARCHAR NOT NULL,
    market_id VARCHAR NOT NULL,
    asset_id VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    outcome VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    price VARCHAR NOT NULL,
    shares VARCHAR NOT NULL,
    transaction_hash VARCHAR,
    outcome_index BIGINT,
    slug VARCHAR,
    event_slug VARCHAR,
    title VARCHAR,
    raw_extra VARCHAR,
    PRIMARY KEY (source_trade_id)
);
"""


def _get_connection(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(CREATE_TABLE_SQL)
    return conn


def write_duckdb(
    trades: list[NormalizedTrade],
    db_path: Path,
) -> tuple[int, int]:
    """Insert trades into DuckDB, skipping duplicates by source_trade_id.

    Returns (inserted_count, skipped_count).
    """
    if not trades:
        return 0, 0

    conn = _get_connection(db_path)
    inserted = 0
    skipped = 0
    for trade in trades:
        row = _trade_to_row(trade)
        try:
            conn.execute(
                """
                INSERT INTO trades VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    row["source"],
                    row["source_trade_id"],
                    row["account"],
                    row["market_id"],
                    row["asset_id"],
                    row["timestamp"],
                    row["outcome"],
                    row["side"],
                    row["price"],
                    row["shares"],
                    row["transaction_hash"],
                    row["outcome_index"],
                    row["slug"],
                    row["event_slug"],
                    row["title"],
                    row["raw_extra"],
                ],
            )
            inserted += 1
        except duckdb.ConstraintException:
            logger.debug("Duplicate source_trade_id skipped: %s", row["source_trade_id"])
            skipped += 1
    conn.close()
    logger.info("DuckDB: inserted=%d skipped=%d", inserted, skipped)
    return inserted, skipped


def load_duckdb(db_path: Path, account: str | None = None) -> list[NormalizedTrade]:
    """Load all (or account-filtered) trades from DuckDB."""
    conn = _get_connection(db_path)
    if account:
        result = conn.execute(
            "SELECT * FROM trades WHERE account = ? ORDER BY timestamp", [account]
        )
    else:
        result = conn.execute("SELECT * FROM trades ORDER BY timestamp")
    columns = [desc[0] for desc in result.description]
    raw_rows = result.fetchall()
    conn.close()
    trades = []
    for raw_row in raw_rows:
        row = dict(zip(columns, raw_row, strict=True))
        trades.append(_row_to_trade(row))
    return trades
