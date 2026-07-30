# Focus-Watchlist Cycle-Resilient Signal Charter

Date: 2026-07-30  
Parent issue: #192  
Implementation issue: #198

## Decision

Alpha Engine will not optimize for a universal stock-selection model as the current research objective. The active system is a **simple, fixed-watchlist, per-security time-series state machine** designed to produce understandable manual trading states across changing market regimes.

Issue #187 stopped further tuning of the broad cross-sectional OHLCV ranker family. It did not invalidate price-based trend and risk-control rules applied independently to a predeclared list. The focus engine does not rank securities, require a fixed number of holdings, or fit separate parameters for each symbol.

## User objective

The system should:

- focus on securities the user actually follows;
- generate a small number of useful trades rather than daily activity;
- wait for trend confirmation and remain invested while the trend survives;
- reduce exposure or exit when the market regime or security structure breaks;
- explain every state from observable inputs;
- support manual execution only;
- improve drawdown behavior without eliminating meaningful upside participation.

A complex model is not required. A deterministic state machine is preferable to a more accurate-looking but unstable black box.

## Frozen focus universe v2

The user-specified list is deduplicated to 19 instruments:

| Symbol | Contract role | Risk tier |
| --- | --- | --- |
| ALAB | signal target | tactical |
| TSM | signal target | core |
| VRT | signal target | core |
| NBIS | signal target | core |
| TSLA | signal target | core |
| QQQ | market regime and benchmark | reference |
| HIMS | signal target | core |
| NOK | signal target | core |
| INTC | signal target | tactical |
| CRDO | signal target | core |
| POET | signal target | tactical |
| IREN | signal target | core |
| SOX | semiconductor-sector context | reference |
| AAOI | signal target | tactical |
| ORCL | signal target | core |
| SNDK | signal target | tactical |
| TIGO | signal target | tactical |
| AMD | signal target | core |
| LITE | signal target | core |

QQQ and SOX are included in every run as reference instruments. They are not passed through the individual-security `ENTER/HOLD/REDUCE/EXIT` engine. QQQ determines the market risk regime. SOX provides an informational semiconductor-cycle regime. The provider alias for the PHLX Semiconductor Sector Index is `^SOX`, while the contract display symbol remains `SOX`.

The other 17 symbols receive trading states from one shared formula. Risk tiers affect only suggested exposure and never alter the signal calculation. Symbols with insufficient history remain visible as `short_history_diagnostic_or_forward_only`; they cannot be silently removed.

## Signal architecture

### 1. Market regime

The market is `risk_on` only when:

- QQQ closes above its 200-session moving average; and
- QQQ's 50-session moving average is above its 200-session moving average.

All other sessions are `risk_off`. SOX is calculated with the same 50/200-session regime labels for context but does not change the v1 entry formula.

### 2. Security trend

A signal target is eligible for entry only when:

- price is above its 100-session moving average;
- the 50-session moving average increased from the prior session;
- 63-session momentum relative to QQQ is positive; and
- price closes above the prior 20-session high, excluding the current session.

### 3. State machine

- `WATCH`: no position and the complete entry condition is absent.
- `ENTER`: market and security conditions are all positive.
- `HOLD`: an open position remains above the 50-session moving average and the stateful 3-ATR trailing stop while QQQ remains risk-on.
- `REDUCE`: the position remains above the structural stop, but medium-term trend or relative strength has weakened.
- `EXIT`: QQQ becomes risk-off, the 3-ATR trailing stop is breached, or required data becomes unavailable while a position is open.

The trailing stop is monotonic while a position is open. Decisions use only information available at the daily close and become actionable no earlier than the next QQQ trading session.

## Implementation contract

The deterministic engine must:

1. ingest a long-form OHLCV file with explicit symbol identities;
2. normalize the provider alias `^SOX` to contract symbol `SOX`;
3. fail if any focus instrument is absent rather than silently shrinking the universe;
4. compute all indicators without future leakage;
5. preserve position state, peak high, trailing stop, prior state, and transition reason codes;
6. output separate signal-target and reference histories;
7. bind the run to hashes of the input data and YAML specification;
8. emit `performance_evaluated=false` and `reserved_performance_opened=false` during implementation.

Required implementation outputs:

- `signal_history.json`;
- `reference_history.json`;
- `current_signals.json`;
- `evidence_manifest.json`;
- `decision.json`.

## Why this can be more cycle-resilient

The system separates three questions that the rejected ranker combined into one score:

1. Is the overall market environment supportive?
2. Is this specific security in an established absolute and relative trend?
3. Has the trend weakened enough to reduce or exit?

The strategy may hold cash. It does not need to select a fixed number of securities in every regime. QQQ and SOX also make market-wide and semiconductor-cycle conditions explicit rather than leaving them embedded in an unstable cross-sectional score.

## Evaluation contract

After implementation passes, #199 must report results for every signal target and the combined signal book:

- strategy return after costs versus same-security buy-and-hold;
- return relative to QQQ;
- maximum drawdown and drawdown reduction;
- upside and downside capture;
- average holding period, turnover, and trades per year;
- 10D and 20D forward returns after each state;
- false exit followed by rapid re-entry;
- contribution concentration by security;
- results in bull, bear, recovery, and sideways/high-volatility regimes;
- context conditioned on the SOX semiconductor regime.

Development targets in the YAML are research gates, not promises of future performance.

## Evidence ledger

- 2021-01-01 through 2025-12-31: `development_observed`.
- 2026-01-01 through 2026-06-30: `falsification_only`.
- 2026-07-01 through 2026-12-31: `independent_reserved` until the half-year and 20-session forward horizon are complete.

The engine may generate forward signals during the reserved period, but #198 may not inspect reserved-period forward returns or performance. No rule, threshold, symbol list, or risk tier may be changed after reserved validation is opened.

## Prohibited work

The v1 challenge does not permit:

- a cross-sectional ranker or fixed Top-K portfolio;
- a model-family comparison;
- a parameter, threshold, or lookback grid;
- per-symbol optimization;
- changing the focus list after viewing performance;
- automatically routing orders to a broker;
- hiding securities or periods that fail.

## Next step

Complete #198 by validating the deterministic implementation and its manifest-bound outputs on fixtures. Real-data cycle validation then proceeds through #199 without opening reserved 2026H2 performance.
