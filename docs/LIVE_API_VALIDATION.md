# Live API Validation

Verification timestamp (UTC): `2026-08-14T17:28:14.372893+00:00`

## Endpoint

`GET https://data-api.polymarket.com/trades`

## Gate status

**PASSED** — live queries completed successfully from a GitHub-hosted runner against the provisionally verified `nagi777` proxy wallet `0xbf337426aa856996b8bb79b238345dd1a0276bf7`.

## Observed facts

- `status(offset=0,limit=5,takerOnly=false): 200`
- response top-level type: `list`
- observed fields: `asset`, `bio`, `conditionId`, `eventSlug`, `icon`, `name`, `outcome`, `outcomeIndex`, `price`, `profileImage`, `profileImageOptimized`, `proxyWallet`, `pseudonym`, `side`, `size`, `slug`, `timestamp`, `title`, `transactionHash`
- observed response timestamp unit by magnitude: **epoch seconds**
- `id` field present in sampled trade: **false**
- `status(offset=10000,limit=1,takerOnly=false): 200`
- `status(offset=10001,limit=1,takerOnly=false): 400`
- `status(with start/end window): 200`

## Identity evidence

The public Polymarket profile for `nagi777` resolves to `0xbf337426aa856996b8bb79b238345dd1a0276bf7`. The same nickname/address mapping is independently corroborated by a public third-party explorer. This identity is sufficient for empirical research use, while raw API/profile evidence should continue to be retained where practical.

## Remaining uncertainties

The live gate establishes request/response compatibility, timestamp units, field presence, offset-bound behavior, and acceptance of maker-inclusive and time-window parameters. It does **not by itself prove** that `takerOnly=false` is semantically exhaustive for every maker-side fill, nor that adjacent `start`/`end` windows have perfectly exclusive boundary semantics. Those properties should be checked during real-history completeness analysis and deduplication.

## Evidence provenance

GitHub Actions workflow: `Empirical validation — nagi777`, run `31824104881`, head commit `18a3c58bf937514927601c62212475a0c2ab167f`.

The workflow uploaded artifact `nagi777-live-api-validation` containing the generated validation report.
