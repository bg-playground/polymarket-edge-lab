# Empirical Timing Robustness Results

## Frozen panel

The live workflow evaluated seven non-overlapping six-hour UTC windows from 2026-08-07 through 2026-08-13, always 12:00-18:00 UTC. The two primary hypotheses and all bucket definitions were frozen before this expanded collection.

All seven collection/analysis windows completed successfully. The workflow artifact retains raw and normalized evidence plus per-window reports and logs.

## Primary hypothesis 1: FIFO complementary-fill lag 61-120 seconds

Classification: **replicated**.

- pooled quantity-weighted pair cost: **0.9116109795** (91.1611c)
- equal-window mean pair cost: **0.8964556657** (89.6456c)
- median window pair cost: **0.9006334323** (90.0633c)
- adequately sized windows below $1: **7 / 7**
- leave-one-window-out pooled range: **0.8847338428 to 0.9272648505**
- paired shares in the primary slice: **32,955.080179**

Per-window pair costs ranged from **0.8353214441** to **0.9878942022**. Every window exceeded the predeclared 500-paired-share adequacy threshold.

## Primary hypothesis 2: FIFO pair formation during market seconds 100-199

Classification: **replicated**.

- pooled quantity-weighted pair cost: **0.9192223358** (91.9222c)
- equal-window mean pair cost: **0.9198268790** (91.9827c)
- median window pair cost: **0.9198560285** (91.9856c)
- adequately sized windows below $1: **6 / 7**
- leave-one-window-out pooled range: **0.8980682891 to 0.9347786523**
- paired shares in the primary slice: **44,509.024018**

One window, 2026-08-13 12:00-18:00 UTC, was above $1 at **1.0106073898**. The pooled result remained below $1 when any single window was removed.

## Full-cohort context

The FIFO full-cohort pair cost itself varied materially by day. Six of the seven historical windows were below $1, ranging from roughly 91.21c to 96.50c; the 2026-08-13 window was about 100.83c. This differs materially from the later six-hour cohort analyzed in PR #7, where the full-cohort FIFO result was above $1.

That regime variation is important. The expanded results support persistence of the two predeclared timing effects in this historical panel, but they do not establish a timeless strategy edge or future profitability.

## Interpretation guardrails

These are historical execution-price accounting results. They do not establish trading intent, realized net P&L, predictive power, or future profitability. No BTC predictive signal, backtest, strategy optimization, machine learning, or live trading was used.
