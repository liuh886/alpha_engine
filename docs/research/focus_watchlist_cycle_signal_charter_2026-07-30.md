# Focus-Watchlist Cycle-Resilient Signal Charter

Date: 2026-07-30  
Parent issue: #192

## Decision

Alpha Engine will not optimize for a universal stock-selection model as the next research objective. The next system is a **simple, fixed-watchlist, per-security time-series signal engine** designed to produce understandable manual trading states across changing market regimes.

This direction is consistent with the final static-to-PIT decomposition. Issue #187 stopped further tuning of the existing broad cross-sectional OHLCV ranker family. It did not invalidate every use of price and volume data. A per-security state machine is a distinct hypothesis: it does not rank a retrospective opportunity set and does not depend on cross-sectional labels.

## User objective

The system should:

- focus on securities the user already follows;
- generate a small number of useful trades rather than daily activity;
- wait for a trend, enter only after confirmation, and remain invested while the trend survives;
- reduce exposure or exit when the market regime or security trend breaks;
- remain simple enough that every signal can be explained from observable inputs;
- support manual execution only;
- improve drawdown behavior without eliminating meaningful upside participation.

A complex model is not a project requirement. A reliable state machine is preferable to a more accurate-looking but unstable black box.

## Frozen v1 focus list

The initial contract uses nine US securities already present in `configs/watchlist.yaml`:

| Symbol | Research role | Risk unit tier |
| --- | --- | --- |
| POET | high-risk tactical technology | tactical |
| IREN | trend-hold infrastructure growth | core |
| HIMS | growth position with disciplined reduction | core |
| BE | tactical high-volatility trend | tactical |
| CRDO | structural growth / pullback candidate | core |
| HIMX | tactical semiconductor cycle exposure | tactical |
| NBIS | structural AI-infrastructure watch | core |
| TSLA | high-beta core trend exposure | core |
| CRCL | short-history event-sensitive exposure | tactical |

The role labels do not change the signal formula. They only bound suggested risk units. QQQ is used as benchmark and market-regime reference; it is not a candidate security.

Symbols with insufficient history remain visible as `short_history_diagnostic_or_forward_only`. They may not be removed after viewing results.

## Signal architecture

The same rule set is applied independently to each security.

### 1. Market regime

The market is `risk_on` only when:

- QQQ closes above its 200-session moving average; and
- QQQ's 50-session moving average is above its 200-session moving average.

All other sessions are `risk_off`. This filter is deliberately slow because the intended strategy is low turnover and trend following.

### 2. Security trend

A security is eligible for entry only when:

- price is above its 100-session moving average;
- the 50-session moving-average slope is positive;
- 63-session momentum relative to QQQ is positive; and
- price closes above the prior 20-session high.

### 3. State machine

- `WATCH`: no position and the full entry condition is absent.
- `ENTER`: market and security conditions are all positive.
- `HOLD`: an open position remains above the 50-session moving average and the 3-ATR trailing stop while the market remains risk-on.
- `REDUCE`: the position remains above the structural stop, but medium-term trend or relative strength has weakened.
- `EXIT`: QQQ becomes risk-off or the security breaches the 3-ATR trailing stop.

All decisions are evaluated at the daily close and are actionable no earlier than the next trading session.

## Why this can be more cycle-resilient

The system separates three questions that a broad ranker combined into one score:

1. Is the overall market environment supportive?
2. Is this specific security in an established absolute and relative trend?
3. Has the trend weakened enough to reduce or exit?

The strategy is allowed to hold cash. It does not need to select a fixed number of securities in every regime. This is the key structural difference from the rejected Top-15 cross-sectional framework.

## Evaluation contract

The first implementation must report results for every security and for the combined signal book.

Primary comparisons:

- signal strategy versus the same security's buy-and-hold return;
- signal strategy versus QQQ;
- maximum drawdown and drawdown reduction;
- upside and downside capture;
- average holding period, turnover, and trades per year;
- 10D and 20D forward returns after each state;
- false exit followed by rapid re-entry;
- profit contribution concentration by security;
- performance in bull, bear, recovery, and sideways/high-volatility regimes.

Development targets are predeclared in the YAML contract. They are research gates, not promises of future performance.

## Evidence ledger

- 2021-01-01 through 2025-12-31: `development_observed`.
- 2026-01-01 through 2026-06-30: `falsification_only`; this period has already been observed in prior project work.
- 2026-07-01 through 2026-12-31: `independent_reserved` until the half-year and the 20-session forward horizon are complete.

No rule, threshold, symbol list, or risk tier may be changed after the reserved evidence is opened.

## Prohibited work

The v1 challenge does not permit:

- a cross-sectional ranker;
- a model-family comparison;
- a parameter, threshold, or lookback grid;
- per-symbol optimization;
- changing the symbol list after viewing performance;
- automatically routing orders to a broker;
- hiding securities or periods that fail.

## Completion of the charter phase

The charter phase is complete when:

1. the YAML specification is merged;
2. contract tests lock the focus list, shared rule set, state vocabulary, manual-execution boundary, and reserved evidence;
3. implementation, validation, and trade-ticket tasks are created as separate issues.

The next engineering step is to implement the deterministic state machine and generate a reproducible signal ledger. No frontend expansion is required before that evidence exists.
