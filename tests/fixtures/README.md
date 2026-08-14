# Test Fixtures

## `trades_page_offset0.json`

Deterministic fixture representing the documented shape of a response from
`GET https://data-api.polymarket.com/trades?user=<account>&offset=0&limit=100`.

**Endpoint:** `https://data-api.polymarket.com/trades`
**Parameters:** `user`, `offset`, `limit`
**Response shape:** JSON array of trade objects.

This fixture was constructed on 2026-08-14 from the official Polymarket Data API
documentation (https://docs.polymarket.com/) and the documented field names
observed in the public API. Network access was unavailable during agent execution,
so this fixture represents the documented shape. See `src/polymarket_edge_lab/normalization/trades.py`
for field mapping assumptions and the "Known Limitations" section of the README.

**Key fields (all confirmed against docs):**
- `id` — trade identifier (string, may be absent; used in dedup hash)
- `market` — condition/market ID (hex string)
- `asset_id` — token/outcome share ID
- `side` — "BUY" or "SELL"
- `size` — share quantity (string-encoded decimal)
- `price` — price per share (string-encoded decimal, 0–1)
- `match_time` — Unix seconds timestamp (string-encoded integer)
- `outcome` — outcome label as returned by API (preserved as-is)
- `owner` — proxy wallet address
- `transaction_hash` — on-chain tx hash (may be null/absent)
