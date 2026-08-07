# QQQ v4.2 Panic Repair Boost — Phase 0 research note

**Date:** 2026-08-07  
**Experiment:** `qqqi_qqq_tqqq_v4_27_panic_repair_boost_research`  
**Parent baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Issue:** #621  
**Status:** research-only; not trade-ready; baseline and alerts unchanged

## Decision

A new information source is worth formal testing:

`QQQ Wilder RSI(14) < 30 × CNN Fear & Greed < 10`

The factor should **not** replace the v4.2 state machine and should **not** buy
TQQQ immediately at the panic close. The useful structure is a sparse event
context:

`deep panic -> arm -> v4.2 repair confirmation -> +25pp TQQQ risk budget`

The existing v4.2 repair semantics remain responsible for timing. Formal state
2 remains exactly 25% QQQ / 75% TQQQ.

## Frozen mechanism

1. A new panic cluster starts when both RSI(14) < 30 and Fear & Greed < 10 at
   the same close.
2. The event only arms one opportunity.
3. The opportunity activates after the existing v4.2 fields confirm:
   - `early_repair`;
   - no `stress_price_failure`;
   - `vix_easing` or `vix_normalized`.
4. The close-time activation is executed once, at the next session open.
5. In executed formal state 0 or 1, exactly 25 percentage points of TQQQ are
   funded pro-rata from the existing non-TQQQ sleeve.
6. The boost ends when formal state 2 arrives or stress price failure returns.
7. No threshold, allocation, delay or duration search is permitted.

## Preliminary actual-product replay

The exploratory replay uses the same v4.2 adjusted-open to adjusted-open return
convention and 10 bps per turnover unit. It is preliminary evidence used to
decide whether implementation is justified, not promotion evidence.

| Metric | current v4.2 | Panic Repair Boost |
|---|---:|---:|
| Total return | 102.23% | 116.63% |
| CAGR | 33.58% | 37.41% |
| Annual volatility | 24.93% | 25.38% |
| Sharpe | 1.287 | 1.380 |
| Sortino | 1.846 | 2.011 |
| Max drawdown | -24.22% | -24.22% |
| Calmar | 1.386 | 1.544 |

The actual QQQI window contains only two qualifying panic clusters and 15
boosted sessions. The headline improvement is therefore promising but
statistically sparse.

## Reliable CNN-history mechanism check

Using only the CNN-authoritative history from 2021-02-01 onward, three
qualifying panic clusters were found:

- 2021-10;
- 2025-04;
- 2026-03.

The frozen repair-boost episodes were positive relative to the same-date QQQ
proxy baseline in all three cases, approximately +3.53%, +4.17%, and +2.13%
respectively. Aggregate proxy CAGR improved by about 2.23 percentage points;
maximum drawdown worsened by about 0.81 percentage points, while Calmar
improved.

This is still too few independent events for promotion.

## Negative control: why not use Fear & Greed < 25

The broader CNN `Extreme Fear` band (<25) adds several events, but it also
admits false repair accelerations around 2022. In the exploratory replay those
extra events materially worsen drawdown.

The experiment therefore freezes `<10`, which came from the original deep-fear
hypothesis, rather than searching the 10-25 range after seeing returns.

## Long-history stress boundary

Pre-2021 Fear & Greed history is reconstructed rather than primary CNN
historical evidence. It can be used only as a lower-confidence mechanism stress
test. Direction over the full archive remains mildly positive, but event
outcomes are mixed. This prevents the recent three-event result from being
treated as proof of a universal rule.

## Architecture decision

The implementation is deliberately small:

- one CNN Fear & Greed adapter with no provider fallback;
- one pure panic/repair state trace;
- one deterministic +25pp TQQQ weight overlay;
- unit tests for timing, missing data, weight conservation and state-2
  preservation;
- no new dependency and no new CI workflow.

This keeps the external sentiment data concern separate from portfolio logic
and grows directly from the existing v4.2 research architecture.

## Next gate

Phase 0 only establishes that the new factor is admissible and worth formal
evidence production. The next experiment should replay actual and reliable
2021+ proxy scopes from governed data, write episode attribution and
chronological diagnostics, and fail closed if the frozen rule is not stable.

Until that evidence exists:

- v4.2 remains the research baseline;
- the current alert source is unchanged;
- no Telegram target changes are authorized;
- `Panic Repair Boost` is not trade-ready.
