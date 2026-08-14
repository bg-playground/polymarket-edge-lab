# Live API Validation

Verification timestamp (UTC): `2026-08-14T16:11:29.128973+00:00`

## Endpoint

`GET https://data-api.polymarket.com/trades`

## Gate status

**BLOCKED** — no verified public proxy wallet configured for `nagi777`, and this sandbox cannot resolve Polymarket hosts for live requests.

## Observed facts

- none (live queries were not possible in this environment)

## Remaining assumptions (must be live-verified)

- response field names and types
- response timestamp unit
- `takerOnly=false` maker-inclusive behavior
- `start`/`end` filter semantics
- ordering semantics
- practical `limit`
- offset `10000` and `10001` behavior
- `id` presence/uniqueness
- undocumented provenance-relevant fields

## How to complete this gate in a network-enabled environment

```bash
python scripts/validate_live_api.py --account 0xVERIFIED_PUBLIC_PROXY_WALLET
```
