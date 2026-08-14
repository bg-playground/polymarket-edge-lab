# Milestone 3C — Seven-day causal feature-panel results

## Status

The Stage 3C GitHub Actions workflow completed successfully on the frozen seven-window historical panel. Standard CI also passed Ruff lint, Ruff format, mypy, and pytest.

## Materialized panel

- Windows: 7 independent six-hour windows, 2026-08-07 through 2026-08-13, 12:00-18:00 UTC.
- Total FIFO pair-event feature rows: 19,644.
- Fully contained BTC five-minute markets across windows: 483.
- SELL-excluded markets: 0.
- Output formats: Parquet panel, CSV inspection sample, JSON coverage report.

Per-window rows / complete markets:

| Window | Rows | Markets | Favorable event ratio |
|---|---:|---:|---:|
| 2026-08-07T12-18Z | 2,374 | 71 | 0.5358 |
| 2026-08-08T12-18Z | 2,507 | 69 | 0.5684 |
| 2026-08-09T12-18Z | 4,483 | 69 | 0.6431 |
| 2026-08-10T12-18Z | 2,281 | 69 | 0.5270 |
| 2026-08-11T12-18Z | 2,904 | 67 | 0.5510 |
| 2026-08-12T12-18Z | 2,186 | 71 | 0.5604 |
| 2026-08-13T12-18Z | 2,909 | 67 | 0.4950 |

`favorable` means FIFO pair cost below $1.00 at the event level and is descriptive only.

## BTC provenance

Independent BTC reference data were collected from the Coinbase Exchange public REST API for BTC-USD at 60-second granularity. The workflow preserved raw responses and a provenance record with the endpoint, requested/observed bounds, retrieval timestamp, raw SHA-256 hash, and candle count.

Observed BTC candle count: 9,009.

## Causal alignment correction

Stage 3C corrected an important timestamp semantic inherited from the original one-second design. `BtcCandle` now carries `interval_seconds`, and a candle becomes observable only at `open_epoch + interval_seconds`. Coinbase 60-second candles are therefore unavailable until their true close time rather than at open+1 second.

The workflow contains an automated assertion that no attached BTC reference timestamp is later than its Polymarket feature-event timestamp.

## Feature coverage at 60-second BTC resolution

The following BTC fields have 100% coverage in every window:

- reference epoch and price;
- 60-second return;
- 120-second return;
- absolute 60-second return;
- return since the five-minute market start;
- range since the five-minute market start.

The following remain intentionally unavailable rather than being synthesized from coarse data:

- 15-second return: 0% coverage;
- 30-second return: 0% coverage;
- 30-second realized volatility: 0% coverage;
- 60-second realized volatility: 0% coverage;
- 120-second realized volatility: 0% coverage.

The realized-volatility fields require enough causal return observations for the current sample-standard definition. With 60-second candles there are not enough observations inside these short horizons to populate them honestly. Stage 3D should either exclude these fields or introduce a separately specified volatility estimator suitable for the available source resolution; it must not backfill or interpolate from future prices.

## Interpretation

Stage 3C establishes a claim-grade event-level dataset suitable for held-out explanatory analysis. It does not establish a tradable signal or future profitability. The next phase should evaluate the frozen global-mean and timing-only baselines first, then compare the predeclared inventory and available BTC feature groups with calendar-day holdouts.
