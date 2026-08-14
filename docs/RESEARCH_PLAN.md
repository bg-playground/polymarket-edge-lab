# Polymarket Edge Lab

## A Quantitative Research Plan for Reconstructing `nagi777` and Testing the 5-Minute Crypto Market-Making Thesis

**Purpose:** Build a reproducible research platform that reconstructs
the public trading behavior of Polymarket trader `nagi777`,
quantitatively tests the claims made about the strategy,
reverse-engineers its economic behavior, and ultimately evaluates
whether a safer or stronger strategy can be discovered through
systematic backtesting and edge-case analysis.

**Status:** Research blueprint. The numerical examples below are
illustrative unless explicitly identified as measured results.

------------------------------------------------------------------------

## 1. Executive Summary

The working hypothesis is that `nagi777` is not primarily making simple
directional bets on whether Bitcoin, Ethereum, or another crypto asset
will move UP or DOWN. Instead, the strategy appears to behave more like
an **inventory-aware high-frequency market maker** in short-duration
Polymarket crypto markets.

The central thesis is:

1.  Acquire UP and DOWN shares at different moments.
2.  Accumulate complementary positions whose combined acquisition cost
    is less than \$1.00.
3.  Treat matched UP + DOWN shares as a complete set that will
    ultimately settle for \$1.00.
4.  Maintain most capital in paired inventory.
5.  Allow a smaller directional residual on the side judged more
    favorable.
6.  Repeat the process across a very large number of short-duration
    markets.

The X post being investigated claims approximately:

-   **51.25 trades per active hour**
-   **\$110.67 average trade**
-   **50% win rate**
-   **\$0.9843 average complete-set cost**
-   **\$0.0157 average gross edge per complete set**
-   **78.7% paired UP+DOWN inventory**
-   **21.3% directional residual**
-   **+\$126,836 profit**

Rather than accepting these figures, the objective of this project is to
reproduce or falsify each one from public data.

The longer-term goal is not merely to clone `nagi777`. It is to build a
research system capable of discovering **when this style of strategy
works, when it fails, and whether systematic modifications improve it
out of sample**.

------------------------------------------------------------------------

## 2. Core Economic Mechanism

A binary Polymarket contract has complementary outcomes. At settlement,
one side pays \$1.00 and the other pays \$0.00.

If one UP share and one DOWN share can be acquired for a combined cost
below \$1.00, the pair has positive gross economics.

For example:

``` text
BUY UP   @ $0.44
BUY DOWN @ $0.53

Combined cost = $0.97
Settlement value = $1.00

Gross edge = $0.03
```

The important feature is that the two shares do **not necessarily need
to be purchased simultaneously**.

Example:

``` text
09:01:02  BUY UP   @ $0.44

Underlying crypto price moves.

09:01:47  BUY DOWN @ $0.40

Combined acquisition cost = $0.84
Settlement value = $1.00
Gross edge = $0.16
```

Real opportunities will generally be much smaller, but repeated small
edges can become meaningful at sufficient volume.

The fundamental quantity is:

\[ `\text{Pair Edge}`{=tex} = 1 - (P\_{UP} + P\_{DOWN}) \]

subject to fees, rebates, fill probability, adverse selection, inventory
risk, and execution costs.

------------------------------------------------------------------------

## 3. Research Philosophy

Treat `nagi777` as a **black-box trading system**.

We observe:

-   market state,
-   public fills,
-   timing,
-   prices,
-   sizes,
-   inventory evolution,
-   underlying crypto movement,
-   and settlement outcomes.

From those observations, we attempt to infer:

-   what conditions trigger trades,
-   how inventory is managed,
-   how complementary positions are accumulated,
-   whether directional residuals contain predictive information,
-   how much P&L comes from pairing versus direction,
-   and which market conditions produce success or failure.

This is behavioral reverse engineering rather than source-code reverse
engineering.

------------------------------------------------------------------------

# Part I --- Data Reconstruction

## 4. Build the Complete Trade Ledger

The first deliverable should be a normalized ledger containing every
obtainable `nagi777` fill.

Recommended fields:

``` text
timestamp
transaction/hash identifier
market identifier
market slug
market start
market expiration
underlying asset
outcome (UP/DOWN)
side (BUY/SELL)
price
shares
notional
fee if available
transaction role if determinable
settlement outcome
```

Illustrative records:

  Timestamp      Market           Outcome   Action     Price   Shares   Notional
  -------------- ---------------- --------- -------- ------- -------- ----------
  07:31:12.421   BTC 7:30--7:35   UP        BUY         .417      100    \$41.70
  07:31:18.773   BTC 7:30--7:35   DOWN      BUY         .566      100    \$56.60
  07:32:04.115   BTC 7:30--7:35   UP        BUY         .391       75    \$29.33

For initial research, **DuckDB + Parquet** is a good choice because it
provides excellent analytical performance without requiring production
database infrastructure.

Suggested flow:

``` text
nagi777 account
      │
      ▼
Polymarket public data
      │
      ├────────► Blockchain OrderFilled events
      │
      ▼
Normalization / validation
      │
      ▼
Parquet + DuckDB
```

Where practical, independently validate API-derived fills against
blockchain events.

------------------------------------------------------------------------

## 5. Reconstruct Inventory Chronologically

For each individual five-minute market, replay fills in timestamp order.

Maintain:

``` text
UP shares
DOWN shares

UP dollars spent
DOWN dollars spent

UP average acquisition cost
DOWN average acquisition cost

paired shares
directional residual
realized sales
fees/rebates
```

Example:

``` text
BUY 100 UP   @ .44
BUY  50 UP   @ .42
BUY  80 DOWN @ .53
BUY  70 DOWN @ .51
```

UP inventory:

\[ 100 + 50 = 150 \]

UP cost:

\[ 100(.44) + 50(.42) = 65 \]

Average UP cost:

\[ 65 / 150 = .4333 \]

DOWN cost:

\[ 80(.53) + 70(.51) = 78.10 \]

Average DOWN cost:

\[ 78.10 / 150 = .5207 \]

Complete-set cost:

\[ .4333 + .5207 = .954 \]

Gross pair edge:

\[ 1-.954=.046 \]

With 150 paired shares:

\[ 150(.046)=\$6.90 \]

This inventory engine is one of the most important pieces of the entire
project.

------------------------------------------------------------------------

## 6. Separate Paired and Directional Inventory

At any point:

\[ `\text{Paired Shares}`{=tex}=`\min`{=tex}(UP,DOWN) \]

\[ `\text{Directional Residual}`{=tex}=\|UP-DOWN\| \]

Example:

``` text
UP   = 1,000
DOWN =   820
```

This represents:

``` text
820 paired UP+DOWN sets
180 directional UP shares
```

This allows us to directly test the X post's claim that approximately:

``` text
78.7% = paired inventory
21.3% = directional residual
```

We should measure this several ways:

-   share-weighted,
-   dollar-weighted,
-   time-weighted,
-   at each fill,
-   at market settlement,
-   and across individual markets.

This prevents an arbitrary accounting convention from creating a
misleading percentage.

------------------------------------------------------------------------

# Part II --- Testing the X Claims

## 7. Test the \$0.9843 Complete-Set Cost

For paired inventory, calculate:

\[ C\_{pair}=P\_{UP}+P\_{DOWN} \]

The claimed mean is:

\[ C\_{pair}=.9843 \]

which implies:

\[ 1-.9843=.0157 \]

or approximately **1.57 cents of gross edge per complete set**.

Report at minimum:

``` text
mean pair cost
median pair cost
standard deviation
5th percentile
25th percentile
75th percentile
95th percentile
percentage below $1.00
percentage below $0.99
percentage below $0.98
```

Also calculate pair edge by:

-   asset,
-   time of day,
-   market age,
-   seconds to expiration,
-   volatility regime,
-   trade size,
-   and directional skew.

------------------------------------------------------------------------

## 8. Avoid Artificially Optimistic Pair Matching

Pair accounting requires care.

Consider:

``` text
09:31:01 BUY UP   .41
09:31:05 BUY UP   .45
09:31:20 BUY DOWN .54
09:31:25 BUY DOWN .51
```

Different accounting conventions produce different apparent pair edges.

### FIFO

``` text
.41 + .54 = .95
.45 + .51 = .96
```

### Weighted Average

``` text
UP average   = .430
DOWN average = .525

Pair cost = .955
```

Potential methods to calculate:

1.  FIFO
2.  weighted-average inventory
3.  LIFO as a sensitivity check
4.  lot-optimized matching only as an explicitly labeled theoretical
    upper bound

Do **not** allow an optimization algorithm to cherry-pick pairings and
then describe the result as the trader's realized edge.

Chronological weighted-average accounting is a strong primary baseline.

------------------------------------------------------------------------

## 9. Reconstruct Full Market Economics

For every market produce a complete accounting record.

Example:

``` text
Market: BTC 7:30–7:35

UP purchases              $423.17
DOWN purchases            $519.42
sales                       $44.21

net capital deployed       $898.38

ending UP shares             910.4
ending DOWN shares           842.7

paired shares                842.7
directional UP                67.7

winning outcome                 UP
settlement value            $910.40

fees/rebates                    $X

net P&L                        $X
```

Then aggregate over the entire dataset.

The objective is to decompose total P&L into:

\[ PnL = PnL\_{paired} + PnL\_{directional} + rebates - fees -
execution costs \]

This decomposition is substantially more informative than headline win
rate.

------------------------------------------------------------------------

## 10. Formal Hypothesis Test Matrix

Convert the viral X post into a test specification.

  -----------------------------------------------------------------------
  Claim                               Measurement
  ----------------------------------- -----------------------------------
  51.25 trades/active hour            fills divided by active trading
                                      hours

  \$110.67 average trade              mean fill notional

  50% win rate                        first determine precisely what
                                      "win" means, then reproduce

  \$0.9843 average pair               reconstructed complete-set
                                      acquisition cost

  \$0.0157 edge                       `1 - average pair cost` before
                                      applicable costs

  78.7% paired                        paired exposure / total exposure

  21.3% directional                   residual exposure / total exposure

  +\$126,836                          reconstructed realized P&L

  simultaneous UP/DOWN orders         historical evidence plus
                                      prospective order-book analysis
  -----------------------------------------------------------------------

Each result should include:

-   measured value,
-   sample size,
-   confidence interval where appropriate,
-   methodology,
-   sensitivity to accounting assumptions,
-   and pass/fail/inconclusive classification.

------------------------------------------------------------------------

# Part III --- Investigating the Directional Residual

## 11. Does the Directional Skew Contain Information?

Suppose the ending inventory is:

``` text
UP   = 1,200
DOWN = 1,000
```

Economically this is:

``` text
1,000 paired sets
+
200 directional UP
```

Now determine whether UP eventually wins.

Repeat across all eligible markets.

Calculate:

\[ P(`\text{winner}`{=tex}=`\text{residual side}`{=tex}) \]

More importantly, bucket the result by residual magnitude.

Example analytical output:

  Residual Exposure     Markets   Residual-Side Win Rate
  ------------------- --------- ------------------------
  0--5%                     ---                      ---
  5--10%                    ---                      ---
  10--20%                   ---                      ---
  20--30%                   ---                      ---
  \>30%                     ---                      ---

If larger residuals correspond to materially higher win rates, inventory
imbalance may encode the trader's confidence.

If residual-side accuracy remains around 50%, the skew may instead be an
incidental consequence of incomplete hedging, fill probability,
inventory constraints, or market-making mechanics.

------------------------------------------------------------------------

## 12. Directional P&L Matters More Than Directional Accuracy

Do not stop at accuracy.

Calculate:

\[ EV\_{directional} \]

because a trader could be correct less than half the time and still make
money if entry prices are favorable.

Measure:

-   residual-side accuracy,
-   average entry price,
-   average payout,
-   expected value per directional share,
-   directional P&L per market,
-   and relationship between skew magnitude and expected value.

------------------------------------------------------------------------

# Part IV --- Aligning Trades With Crypto Market Data

## 13. Add Underlying Crypto Prices

For every fill, capture the contemporaneous underlying price.

Example:

``` text
TIME           BTC        NAGI

12:01:12.120   68,421     BUY UP .43
12:01:16.822   68,448
12:01:20.314   68,476     BUY DOWN .54
12:01:21.883   68,461
12:01:28.119   68,437     BUY UP .46
```

Potential external features:

``` text
BTC return 250 ms
BTC return 1 sec
BTC return 2 sec
BTC return 5 sec
BTC return 10 sec
BTC return 30 sec
BTC return 60 sec

realized volatility
spot bid/ask spread
spot order-book imbalance
perpetual futures movement
volume
trade imbalance
distance from five-minute opening/reference price
```

The research question becomes:

> What observable market conditions systematically precede `nagi777`
> trades?

------------------------------------------------------------------------

## 14. Perform Event Studies

Normalize thousands of similar fills around time zero.

Example:

``` text
                NAGI BUYS UP
                     ↓
-10s   -5s   -1s     0     +1s   +5s   +10s
─────────────────────┼───────────────────────
```

Calculate average and distributional underlying returns before and
after:

-   UP purchases,
-   DOWN purchases,
-   large trades,
-   small trades,
-   initial inventory entries,
-   complementary/hedging entries,
-   and large directional-skew changes.

This can distinguish hypotheses such as:

### Mean Reversion

``` text
BTC falls
↓
nagi buys UP
↓
BTC partially rebounds
```

### Momentum

``` text
BTC rises
↓
nagi buys UP
↓
BTC continues rising
```

### Inventory Rebalancing

``` text
DOWN inventory becomes excessive
↓
UP becomes sufficiently cheap
↓
nagi buys UP regardless of directional signal
```

The data should determine which explanation is strongest.

------------------------------------------------------------------------

# Part V --- Polymarket Microstructure

## 15. Analyze Polymarket Price Movement Around Fills

For each fill obtain, where possible:

\[ P\_{t-10},P\_{t-5},P\_{t-1},P_t,P\_{t+1},P\_{t+5},P\_{t+10} \]

Questions include:

-   Does the trader tend to buy after price declines?
-   Does price move favorably immediately after the fill?
-   Is the trader being adversely selected?
-   Are fills predominantly liquidity-providing or liquidity-taking?
-   How frequently does a first leg eventually receive a profitable
    complementary fill?
-   How long does completion usually take?

One especially important metric is:

\[ P(`\text{profitable complement acquired within }`{=tex} N
`\text{ seconds}`{=tex}) \]

This may be more valuable than simply predicting whether BTC finishes UP
or DOWN.

------------------------------------------------------------------------

## 16. Historical Reconstruction Has Limits

Historical public fills can reveal completed trades extremely well, but
they may not reveal the complete lifecycle of every limit order that
was:

-   posted,
-   modified,
-   cancelled,
-   or never filled.

Therefore the claim that the trader always places simultaneous UP and
DOWN limit orders should be treated separately from claims that can be
directly established from fills.

Classification:

``` text
Directly measurable:
✓ fills
✓ prices
✓ quantities
✓ timing
✓ inventory
✓ settlements
✓ reconstructed P&L

Potentially inferable:
~ maker/taker behavior
~ simultaneous quoting behavior
~ unfilled quote strategy

Not safely reconstructable from fills alone:
✗ every historical unfilled/cancelled order
```

------------------------------------------------------------------------

# Part VI --- Start a Prospective Data Collector

## 17. Archive High-Resolution Market Data Going Forward

Historical reconstruction should be paired with a prospective collector
running continuously.

Capture:

``` text
Polymarket order-book updates
Polymarket public trades
crypto spot prices
crypto spot order books
perpetual futures data if useful
market metadata
market reference/opening prices
nagi777 fills
timestamps with consistent precision
```

This creates two complementary datasets.

### Historical Dataset

``` text
nagi fills
market prices
settlements
crypto prices where obtainable
blockchain events
```

### Prospective Dataset

``` text
full high-resolution order book
all observed trades
crypto order book
precise timestamps
nagi fills
```

The prospective dataset allows much stronger microstructure analysis.

------------------------------------------------------------------------

# Part VII --- Blockchain Ground Truth

## 18. Independently Validate Trades

Where feasible, use blockchain `OrderFilled` events as a second source
of truth.

Architecture:

``` text
Polymarket API ─────────┐
                       │
                       ▼
                  reconciliation
                       ▲
                       │
Blockchain events ─────┘
```

Flag discrepancies such as:

``` text
missing API fill
duplicate fill
timestamp disagreement
side disagreement
quantity disagreement
price disagreement
market mapping failure
```

This is particularly valuable because errors in the foundational trade
ledger will contaminate every downstream inference.

------------------------------------------------------------------------

# Part VIII --- Reverse Engineering the Strategy

## 19. Build a Decision Dataset

Once the ledger is reliable, create feature vectors representing the
state surrounding each decision.

Example:

``` text
BTC_1s_return             .00042
BTC_5s_return             .00117
BTC_30s_return            .00081
BTC_volatility            .00214

PM_UP_price               .413
PM_DOWN_price             .579

UP_depth                  1842
DOWN_depth                2204
spread                     .012

seconds_remaining           173
distance_from_open          +22

current_UP_inventory        420
current_DOWN_inventory      516

paired_inventory            420
directional_DOWN             96

ACTION                   BUY UP
```

Potential target classes:

``` text
NO TRADE
BUY UP
BUY DOWN
BUY BOTH / PAIR
SELL / REDUCE
```

------------------------------------------------------------------------

## 20. Start With Interpretable Models

Do **not** begin with a neural network.

Recommended progression:

1.  logistic regression
2.  decision tree
3.  random forest
4.  gradient-boosted trees such as XGBoost/LightGBM
5.  neural network only when justified by evidence

The objective initially is explanation.

A decision tree might reveal a rule resembling:

``` text
IF BTC_5sec_return < threshold
AND UP_price < threshold
AND seconds_remaining > threshold
AND UP_inventory < DOWN_inventory

THEN probability(BUY UP) increases sharply
```

That gives us an economically interpretable hypothesis.

A neural network reporting 72% classification accuracy without
explaining the behavior is less useful during reverse engineering.

------------------------------------------------------------------------

## 21. Measure Reconstruction Quality Out of Sample

Split the data chronologically.

Example:

``` text
Training period:    first 70%
Validation period:  next 10%
Holdout period:     final 20%
```

Never randomly mix future trades into training data when evaluating a
time-dependent strategy.

Potential metrics:

``` text
trade/no-trade precision
UP/DOWN action accuracy
trade-size correlation
inventory-skew correlation
paired-cost similarity
P&L similarity
market-level behavior similarity
```

The strongest validation is not simply predicting individual fills.

It is reproducing the **economic fingerprint**:

``` text
paired inventory %
directional residual %
average pair cost
trade frequency
trade size
P&L distribution
inventory trajectory
```

------------------------------------------------------------------------

# Part IX --- Build a Replay / Backtesting Engine

## 22. Deterministic Historical Replay

The backtester should reproduce market state chronologically and expose
information only when it would actually have been available.

Conceptually:

``` text
Historical event stream
        │
        ▼
Virtual market state
        │
        ▼
Strategy
        │
        ▼
Simulated orders
        │
        ▼
Fill model
        │
        ▼
Inventory
        │
        ▼
Settlement / P&L
```

The engine must model:

-   bid/ask spread,
-   available depth,
-   partial fills,
-   order latency,
-   fees,
-   maker rebates,
-   cancellations,
-   time priority assumptions,
-   market expiration,
-   and inventory constraints.

A strategy that works only under unrealistic instantaneous fills is not
a valid strategy.

------------------------------------------------------------------------

## 23. Establish Baseline Strategies

Before introducing AI, compare several deterministic baselines.

### Strategy A --- Pure Complete-Set Arbitrage

Only acquire positions when the combined executable cost is below a
defined threshold.

### Strategy B --- Two-Sided Market Making

Continuously quote both sides around estimated fair value.

### Strategy C --- Inventory-Skew Market Making

Adjust quotes according to existing UP/DOWN inventory.

### Strategy D --- Nagi-Style Reconstructed Strategy

Implement the behavioral rules inferred from the forensic analysis.

### Strategy E --- ML-Assisted Inventory Strategy

Use statistical models for fill probability, adverse selection,
complement acquisition, and/or fair value.

Every advanced strategy must beat simpler baselines **after realistic
costs**.

------------------------------------------------------------------------

# Part X --- Edge-Case Discovery

## 24. Turn Losing Trades Into a Research Dataset

For every losing or underperforming market, record hundreds of
potentially relevant conditions.

Examples:

``` text
underlying volatility
short-term momentum
order-book imbalance
spread
depth
seconds remaining
inventory imbalance
pair cost
first-leg price
time between complementary fills
trade size
market liquidity
recent fill rate
underlying distance from reference price
```

The research system can search for conditional failure modes.

Illustrative hypothesis:

``` text
Baseline pair edge:
+1.42 cents

BUT WHEN:

BTC 5-second volatility > 97th percentile
AND
time remaining < 35 seconds
AND
order-book imbalance > 3.2

observed result:
-2.17 cents
```

That becomes a candidate exclusion rule.

------------------------------------------------------------------------

## 25. Statistical Validation Is Mandatory

A discovered rule must not immediately become part of the strategy.

Workflow:

``` text
Observation
    ↓
Hypothesis
    ↓
Training-data test
    ↓
Validation-data test
    ↓
Holdout test
    ↓
Multiple-testing correction / robustness checks
    ↓
Paper trading
    ↓
Candidate promotion
```

This protects against discovering patterns that exist purely by chance.

The more hypotheses an automated agent tests, the more important this
becomes.

------------------------------------------------------------------------

# Part XI --- Multi-Agent / LangGraph Architecture

## 26. Use Agents as Quantitative Researchers, Not Traders

A LangGraph-style system makes sense primarily for research automation.

Possible graph:

``` text
                 Research Coordinator
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   Failure Analyst   Pattern Agent   Market Analyst
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                Hypothesis Generator
                         │
                         ▼
                  Backtest Agent
                         │
                         ▼
              Statistical Validator
                         │
                         ▼
                Adversarial Agent
                         │
                         ▼
                 Strategy Registry
```

### Failure Analysis Agent

Examines losing markets and identifies unusual shared characteristics.

### Hypothesis Agent

Converts observations into explicit, machine-testable rules.

### Backtest Agent

Runs approved experiments using the deterministic replay engine.

### Statistical Validation Agent

Checks significance, robustness, holdout performance, and potential
overfitting.

### Adversarial Agent

Attempts to break apparently successful strategies by testing:

-   different periods,
-   volatility regimes,
-   assets,
-   fee assumptions,
-   latency assumptions,
-   fill assumptions,
-   and extreme markets.

### Strategy Registry

Stores every experiment:

``` text
hypothesis
code/version
dataset version
training period
validation period
holdout period
results
status
reason promoted/rejected
```

------------------------------------------------------------------------

# Part XII --- Potential Machine-Learning Targets

## 27. Predict Microstructure Events Rather Than Only UP/DOWN

A neural network may eventually be useful, but potentially more useful
targets exist than predicting the final binary outcome.

Examples:

\[ P(`\text{UP price rises ≥3¢ within 15 seconds}`{=tex}) \]

\[
P(`\text{complementary share reaches profitable price within 20 seconds}`{=tex})
\]

\[ P(`\text{our limit order fills before adverse price movement}`{=tex})
\]

\[ E(`\text{maximum favorable excursion}`{=tex}) \]

\[ E(`\text{adverse selection after fill}`{=tex}) \]

\[ E(`\text{future complete-set acquisition cost}`{=tex}) \]

These directly address the economics of inventory construction.

A particularly interesting model is:

\[ P(`\text{profitable complement fill}`{=tex}
`\mid `{=tex}`\text{current market state}`{=tex}) \]

That may be more valuable than:

\[ P(BTC finishes UP) \]

------------------------------------------------------------------------

# Part XIII --- Production Execution Architecture

## 28. Keep the Live Execution Layer Deterministic

The eventual architecture should separate intelligence from execution.

``` text
Market Data
    │
    ▼
Feature Engine
    │
    ▼
Statistical / ML Models
    │
    ▼
Strategy Engine
    │
    ▼
Risk Engine
    │
    ▼
Deterministic Order Manager
    │
    ▼
Polymarket
```

An LLM should **not** directly control wallet signing or decide ad hoc
to send trades.

Live execution should operate under explicit rules such as:

``` python
if (
    expected_edge_after_costs > minimum_edge
    and inventory_risk < maximum_inventory
    and estimated_adverse_selection < threshold
    and seconds_remaining > minimum_time
    and daily_loss < daily_loss_limit
):
    submit_approved_limit_order()
```

The exact implementation would be developed and tested later.

------------------------------------------------------------------------

# Part XIV --- Risk Controls

## 29. Risk Is a First-Class System

Before live trading, define hard controls including:

``` text
maximum position per market
maximum directional residual
maximum total exposure
maximum daily loss
maximum consecutive losses
maximum order rate
minimum estimated edge
minimum liquidity
minimum seconds remaining
maximum acceptable spread
maximum latency
stale-data cutoff
API failure behavior
WebSocket disconnect behavior
duplicate-order prevention
wallet balance checks
emergency kill switch
```

Every risk rule should have automated tests.

The default response to uncertain system state should be **no new
exposure**.

------------------------------------------------------------------------

# Part XV --- QA and Reproducibility

## 30. Treat the Trading Platform Like a Safety-Critical Automation System

Every important transformation should be independently testable.

Examples:

### Inventory Tests

``` text
buy UP
buy DOWN
partial pairing
multiple price lots
sell inventory
settlement
```

### P&L Tests

``` text
UP wins
DOWN wins
perfectly paired inventory
directional residual
fees
rebates
partial fills
```

### Replay Tests

Given identical input data and strategy version:

``` text
same events
+
same configuration
=
same result
```

### Regression Tests

When a strategy changes, automatically compare:

``` text
old P&L
new P&L

old drawdown
new drawdown

old pair cost
new pair cost

old inventory risk
new inventory risk
```

No strategy change should be promoted merely because total historical
P&L increased.

------------------------------------------------------------------------

# Part XVI --- Proposed GitHub Repository

## 31. Repository Structure

``` text
polymarket-edge-lab/

├── README.md
├── pyproject.toml
├── .env.example
├── config/
│   ├── research.yaml
│   └── risk.yaml
│
├── collectors/
│   ├── polymarket_trades.py
│   ├── polymarket_books.py
│   ├── blockchain_events.py
│   └── crypto_market_data.py
│
├── data/
│   ├── raw/
│   ├── normalized/
│   └── parquet/
│
├── reconstruction/
│   ├── inventory.py
│   ├── pairing.py
│   ├── pnl.py
│   └── settlements.py
│
├── analysis/
│   ├── nagi_profile.py
│   ├── claim_validation.py
│   ├── event_study.py
│   ├── directional_skew.py
│   ├── pair_edge.py
│   └── execution_analysis.py
│
├── features/
│   ├── crypto_features.py
│   ├── polymarket_features.py
│   └── inventory_features.py
│
├── models/
│   ├── logistic.py
│   ├── decision_tree.py
│   ├── gradient_boosting.py
│   └── neural_net.py
│
├── backtester/
│   ├── replay_engine.py
│   ├── order_book.py
│   ├── fills.py
│   ├── fees.py
│   ├── inventory.py
│   └── metrics.py
│
├── strategies/
│   ├── complete_set.py
│   ├── market_maker.py
│   ├── inventory_skew.py
│   └── reconstructed_nagi.py
│
├── agents/
│   ├── coordinator/
│   ├── hypothesis_agent/
│   ├── failure_analysis_agent/
│   ├── statistical_validation_agent/
│   └── adversarial_agent/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── replay/
│   └── regression/
│
└── notebooks/
    ├── 01_nagi_reconstruction.ipynb
    ├── 02_claim_validation.ipynb
    ├── 03_pair_analysis.ipynb
    ├── 04_directional_edge.ipynb
    ├── 05_event_study.ipynb
    └── 06_strategy_inference.ipynb
```

------------------------------------------------------------------------

# Part XVII --- Development Roadmap

## 32. Milestone 1 --- Acquire the Historical Dataset

**Goal:** Obtain and normalize the full public `nagi777` fill history.

Deliverables:

-   raw trade archive,
-   normalized Parquet dataset,
-   market metadata mapping,
-   settlement mapping,
-   validation report.

Do not proceed until the ledger passes consistency checks.

------------------------------------------------------------------------

## 33. Milestone 2 --- Reproduce Aggregate Trading Statistics

Calculate:

-   total fills,
-   unique markets,
-   active hours,
-   trades per active hour,
-   average trade size,
-   median trade size,
-   total notional,
-   asset distribution,
-   activity by hour/day.

Compare directly with the X claims.

------------------------------------------------------------------------

## 34. Milestone 3 --- Reconstruct Inventory

Build the chronological inventory engine and calculate:

-   UP inventory,
-   DOWN inventory,
-   paired inventory,
-   residual inventory,
-   average acquisition costs,
-   market-level trajectories.

This is the foundation for the remaining analysis.

------------------------------------------------------------------------

## 35. Milestone 4 --- Test the 98.43¢ / 1.57¢ Claim

Calculate complete-set economics under clearly documented accounting
rules.

Primary question:

> Does `nagi777` actually construct paired inventory for approximately
> \$0.9843 on average?

------------------------------------------------------------------------

## 36. Milestone 5 --- Test the 78.7% / 21.3% Claim

Determine whether capital/exposure is approximately:

``` text
78.7% paired
21.3% directional
```

Measure this under multiple reasonable definitions.

------------------------------------------------------------------------

## 37. Milestone 6 --- Reconstruct P&L

Decompose:

``` text
paired P&L
directional P&L
fees
rebates
other measurable effects
```

Then determine whether the reported approximately \$126,836 profit is
reproducible for the same period.

------------------------------------------------------------------------

## 38. Milestone 7 --- Add Crypto Market Data

Align fills with BTC/ETH/etc. and conduct event studies.

Determine whether trading behavior is associated with:

-   momentum,
-   mean reversion,
-   volatility,
-   reference-price distance,
-   or primarily inventory rebalancing.

------------------------------------------------------------------------

## 39. Milestone 8 --- Infer Behavioral Rules

Build interpretable statistical models.

Attempt to predict:

``` text
NO TRADE
BUY UP
BUY DOWN
PAIR/REBALANCE
```

Determine which features have the greatest explanatory power.

------------------------------------------------------------------------

## 40. Milestone 9 --- Build the Replay Engine

Create realistic historical simulation including:

-   order-book depth,
-   latency,
-   partial fills,
-   fees,
-   rebates,
-   inventory,
-   expiration.

Use it to test the reconstructed strategy independently.

------------------------------------------------------------------------

## 41. Milestone 10 --- Automated Edge-Case Research

Introduce the agentic research layer.

Its mission:

> Find repeatable conditions under which the reconstructed strategy
> significantly overperforms or underperforms its baseline expectation.

Every proposed improvement must survive unseen data.

------------------------------------------------------------------------

## 42. Milestone 11 --- Prospective Paper Trading

Run the system against live data without risking capital.

Compare:

``` text
predicted fills
vs.
realistically achievable fills

predicted pair edge
vs.
realized simulated pair edge

predicted P&L
vs.
paper P&L
```

Run long enough to observe multiple volatility and liquidity regimes.

------------------------------------------------------------------------

## 43. Milestone 12 --- Controlled Live Experiment

Only after successful historical and prospective validation should live
execution even be considered.

Begin with deliberately small exposure and hard risk limits.

Research success does not imply future profitability.

------------------------------------------------------------------------

# Part XVIII --- Key Research Questions

## 44. Questions the Project Should Answer

1.  Can the reported trade count and average size be reproduced?
2.  Is the average complete-set acquisition cost actually near \$0.9843?
3.  Does paired inventory account for approximately 78.7% of exposure?
4.  Is the remaining 21.3% intentionally directional?
5.  Does the directional residual predict the winning outcome?
6.  Does larger directional skew imply greater predictive confidence?
7.  How much P&L comes from paired inventory?
8.  How much comes from directional exposure?
9.  How important are maker rebates and fees?
10. How long does it typically take to complete a pair?
11. What percentage of first legs never obtain a profitable complement?
12. Under what conditions does incomplete inventory become dangerous?
13. Is the trader responding to crypto momentum or mean reversion?
14. Does Polymarket lag the underlying crypto market?
15. Does the strategy exploit that lag?
16. How does performance change as expiration approaches?
17. Which volatility regimes are favorable?
18. Which volatility regimes destroy the apparent edge?
19. Can an interpretable model reproduce the trader's behavior?
20. Can a modified strategy outperform the reconstructed baseline out of
    sample?

------------------------------------------------------------------------

# Part XIX --- The Most Important Conceptual Shift

## 45. Do Not Frame the Problem as Simply Predicting Bitcoin

The obvious question is:

> Will Bitcoin be UP or DOWN five minutes from now?

That may not be the most valuable question.

Potentially better questions are:

> If we buy UP at \$0.43 now, what is the probability that DOWN becomes
> available cheaply enough within the next 20 seconds to create a
> complete set below \$0.985?

or:

> If our UP limit order fills, what is the probability that we were
> adversely selected?

or:

> Given our current inventory, what price makes adding the complementary
> side positive expected value?

This transforms the project from a binary prediction bot into a
**microstructure and inventory optimization system**.

------------------------------------------------------------------------

# Part XX --- Definition of Success

## 46. Phase-One Success

The initial project succeeds if it can independently produce a
defensible report resembling:

``` text
NAGI777 FORENSIC REPORT

Markets analyzed:              X
Fills analyzed:                X
Total notional:               $X

Trades/active hour:            X
Average trade:                $X

Average paired cost:           X
Median paired cost:            X
Gross paired edge:             X

Paired exposure:               X%
Directional residual:          X%

Paired P&L:                   $X
Directional P&L:              $X
Fees/rebates:                 $X
Reconstructed total P&L:      $X

Residual-side win rate:        X%
Correlation of skew/win:       X

X-post claim assessment:
SUPPORTED / PARTIALLY SUPPORTED / NOT SUPPORTED / INCONCLUSIVE
```

Only after producing this report should significant effort be spent on a
neural network or autonomous strategy-discovery system.

------------------------------------------------------------------------

# Part XXI --- Guiding Principles

## 47. Rules for the Project

1.  **Measure before modeling.**
2.  **Reconstruct before imitating.**
3.  **Use simple models before neural networks.**
4.  **Separate paired P&L from directional P&L.**
5.  **Never ignore fees, rebates, latency, or fill probability.**
6.  **Never optimize on the holdout dataset.**
7.  **Treat every discovered edge as guilty of overfitting until proven
    otherwise.**
8.  **Require deterministic, reproducible backtests.**
9.  **Keep LLM agents away from direct wallet control.**
10. **Use agents for hypothesis generation and research automation.**
11. **Use deterministic code for accounting, risk, and execution.**
12. **Paper trade before risking capital.**
13. **Prefer economic understanding over impressive model accuracy.**
14. **Preserve every experiment and rejected hypothesis.**
15. **Build the data and testing infrastructure as if bad assumptions
    cost real money---because eventually they could.**

------------------------------------------------------------------------

# Recommended Immediate Next Step

Do **not** start with LangGraph or a neural network.

Start with:

``` text
STEP 1
Identify and verify nagi777's account/wallet

        ↓

STEP 2
Download every obtainable historical fill

        ↓

STEP 3
Normalize and independently validate the ledger

        ↓

STEP 4
Reconstruct UP/DOWN inventory market by market

        ↓

STEP 5
Calculate paired cost and directional residual

        ↓

STEP 6
Test the X post's quantitative claims

        ↓

STEP 7
Only then begin reverse-engineering the strategy
```

The first concrete software deliverable should therefore be a
**historical trade collector plus forensic reconstruction engine**, not
a trading bot.

That gives the project a factual foundation from which every later
decision---machine learning, LangGraph agents, paper trading, or live
execution---can be evaluated objectively.

------------------------------------------------------------------------

## Working Project Name

**Polymarket Edge Lab**

Possible subtitle:

> *Forensic reconstruction, market-microstructure research, and
> systematic edge discovery for short-duration prediction markets.*

------------------------------------------------------------------------

## Disclaimer

This project is intended for quantitative research and software
experimentation. Historical trading performance and reconstructed
historical edges do not establish that the same strategy will remain
profitable. Prediction-market trading can result in substantial losses,
particularly when leverage-like exposure, incomplete hedging, latency,
liquidity constraints, model error, or unexpected market behavior are
involved. Any eventual live system should use strict risk controls and
only capital that can be lost without material consequence.
