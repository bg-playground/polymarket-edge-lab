# Test Fixtures

## `trades_page_offset0.json`

Deterministic fixture representing the documented shape of a response from
`GET https://data-api.polymarket.com/trades?user=<account>&offset=0&limit=100`.

**Endpoint:** `https://data-api.polymarket.com/trades`
**Parameters:** `user`, `offset`, `limit`
**Response shape:** JSON array of trade objects.

**Schema status:** Field names verified against official Polymarket Data API
documentation (https://docs.polymarket.com/) and the public developer cheatsheet
(as of 2026-08-14).  Live response shape not confirmed due to network restriction
during agent execution.
TODO: Verify field names, types, and timestamp unit against a live response
before production use.  Update this fixture from a real small sample when
network access is available.

**Documented Data API fields (this fixture):**
- `id` — trade identifier (string; may be absent)
- `conditionId` — condition/market ID (hex string)
- `asset` — CTF token ID for the specific outcome share (numeric string)
- `side` — "BUY" or "SELL"
- `size` — share quantity (**JSON number**, parsed with `parse_float=Decimal`)
- `price` — price per share (**JSON number** 0–1, parsed with `parse_float=Decimal`)
- `timestamp` — Unix **milliseconds** integer
- `outcome` — outcome label as returned by API (preserved as-is)
- `outcomeIndex` — numeric outcome index (integer, may be absent)
- `proxyWallet` — proxy wallet address
- `transactionHash` — on-chain tx hash (may be null/absent)
- `slug` — market slug (may be absent)
- `eventSlug` — event slug (may be absent)
- `title` — market question/title (may be absent)

**Important distinctions from CLOB API shape:**
- `conditionId` (not `market`)
- `asset` (not `asset_id`)
- `proxyWallet` (not `owner`)
- `timestamp` in **milliseconds** (not `match_time` in seconds)
- `transactionHash` camelCase (not `transaction_hash`)
- `price` and `size` are **JSON numbers**, not strings
