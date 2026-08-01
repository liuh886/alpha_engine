# QQQI / QQQ / TQQQ Strategy Experiment Ledger

Last updated: 2026-08-01

## Purpose

This ledger is the durable decision record for the QQQI / QQQ / TQQQ rotation research line. It complements the versioned YAML contracts, result reports, evidence archives, GitHub pull requests and `StrategyExperimentJournal` run records.

The ledger records:

- what hypothesis was tested;
- what was frozen and what changed;
- the common sample and execution convention;
- the result and attribution;
- whether the result was independent or generated after observing an earlier result;
- the promotion boundary and next admissible question.

A strong in-sample metric is not sufficient for strategy promotion.

## Shared research boundary

Unless a contract states otherwise:

- tradable instruments: QQQI, QQQ and TQQQ;
- signal generation: session close;
- execution: next session adjusted open;
- return measurement: adjusted open to adjusted open;
- transaction cost: 10 basis points per turnover unit;
- common three-asset sample: 2024-01-30 through 2026-07-30 economic returns;
- observations: 627;
- no pre-inception backfill for QQQI;
- all strategies remain `research_only=true` and `trade_ready=false`.

The short QQQI history is the principal evidence limitation. Results from this common window cannot establish robustness across 2018, 2020 or 2022.

## Experiment lineage

| Version | PR | Merge commit | Primary change | Decision |
|---|---:|---|---|---|
| Price-only v1 | #261 | `69dbbbdc40aee2e28f75065f02bd48174ad1cf1b` | Initial MA200-oriented three-asset rotation | Reject as primary architecture; recovery clock was too slow |
| Price-repair v2 / VIX v2 | #261 | `69dbbbdc40aee2e28f75065f02bd48174ad1cf1b` | Multi-stage price repair and 50% TQQQ state; VIX as risk-budget overlay | Retain architecture; VIX improves drawdown and Calmar but is not the return engine |
| VIX v3 aggressive | #262 | `9b1b39228b1f99f2575f010f73977d61ab193684` | Increase partial-leverage state from 50% to 75% TQQQ | Retain as research challenger; higher participation improves return but amplifies false starts |
| Breadth / VXN v4 | #265 | `dd5cfb9beb7c6dd98669f56fc9921ea58fc40d87` | Test QQQE/QQQ breadth gate, VXN replacement and VIX/VXN dual confirmation | Reject relative breadth hard gate; retain VXN as incremental Nasdaq-specific information |
| VXN leverage veto v4.1 | #266 | `64cfb85dddf0019abaec42f101281477c7d31f9a` | Preserve VIX state machine; use VXN only to veto the 75% TQQQ layer | Leading future out-of-sample monitoring candidate; not trade ready |

## Result summary

| Strategy | CAGR | Annual volatility | Sharpe | Max drawdown | Calmar | Total return |
|---|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 22.01% | 21.30% | 1.041 | -24.17% | 0.911 | 64.06% |
| Price-only v1 | 20.39% | 20.80% | 0.997 | -23.69% | 0.861 | — |
| Price-repair v2, 50% TQQQ, no VIX | 29.33% | 26.03% | 1.119 | -27.48% | 1.068 | — |
| VIX v2, 50% TQQQ | 26.67% | 24.29% | 1.095 | -23.23% | 1.148 | 80.09% |
| VIX v3, 75% TQQQ | 29.62% | 26.63% | 1.108 | -24.43% | 1.212 | 90.68% |
| VIX v3 + QQQE/QQQ hard breadth gate | 17.19% | 23.23% | 0.800 | -24.43% | 0.703 | 48.38% |
| VXN replaces VIX | 30.12% | 25.58% | 1.158 | -26.30% | 1.145 | 92.53% |
| VIX + VXN full dual confirmation | 29.62% | 24.97% | 1.164 | -26.30% | 1.126 | 90.69% |
| **VIX v3 + VXN leverage veto v4.1** | **32.44%** | **25.82%** | **1.218** | **-24.43%** | **1.328** | **101.17%** |

## Findings by experiment

### Price repair and VIX v2

The price-repair architecture, not VIX, generated the return opportunity. Relative to the matched price-repair strategy without VIX, the VIX overlay reduced CAGR but improved maximum drawdown and Calmar.

Current interpretation:

1. QQQ drawdown provides shock memory.
2. Short- and medium-horizon price repair identifies a recovery opportunity.
3. VIX regulates broad-market risk budget and tail exposure.
4. MA200 is a long-term defensive boundary, not the primary recovery clock.

### VIX v3: 75% TQQQ

Increasing TQQQ weight from 50% to 75% preserved the exact timing trace and improved CAGR, total return and Calmar. It did not improve hit rate. Most incremental gain came from two long recovery episodes, while short false starts became more expensive.

Decision: retain 75% as a named challenger, but do not search the current sample for an apparently optimal leverage weight.

### Relative breadth v4

The frozen gate required `QQQE / QQQ` to be above its 20-session average with positive five-session momentum before entering the 75% TQQQ state.

It removed 106 of 141 leveraged sessions, reduced CAGR by 12.43 percentage points and did not improve maximum drawdown. It blocked both weak starts and important mega-cap-led recoveries.

Decision: reject equal-weight relative outperformance as a hard gate for a cap-weighted QQQ/TQQQ recovery strategy. This does not reject all breadth information. It rejects this specific proxy, transformation and hard-gate role.

### VXN v4

VIX and VXN were highly correlated, but VXN identified additional Nasdaq-specific stress sessions. Replacing VIX across the full state machine changed too much of the QQQI/QQQ path, while full dual confirmation was too defensive.

Decision: VXN contains incremental information, but its role should be narrow and aligned with Nasdaq leverage exposure.

### VXN leverage veto v4.1

VIX and price rules continue to control QQQI defense and initial QQQ repair. VXN only determines whether the 75% TQQQ layer is permitted and can return the strategy from leveraged exposure to QQQ.

Relative to VIX v3, v4.1 produced:

- CAGR: +2.82 percentage points;
- annual volatility: -0.81 percentage points;
- Sharpe: +0.110;
- maximum drawdown: unchanged;
- Calmar: +0.115;
- total return: +10.49 percentage points;
- leveraged sessions: 141 to 129;
- leveraged-state cumulative net return: 46.50% to 60.22%;
- worst leveraged day: -8.77% to -7.85%.

The QQQI defensive state remained exactly unchanged, supporting the intended attribution: VXN improved the leveraged layer rather than rewriting the broad-market state machine.

However, v4.1 was formulated after observing v4. It is explicitly a post-result hypothesis. The early chronological segment was slightly weaker and the late segment materially stronger. It therefore cannot be promoted from the observed sample.

## Evidence references

| Version | Workflow run | Artifact ID | Evidence digest |
|---|---:|---:|---|
| VIX v2 | `30688386902` | — | `sha256:c1c6ced0f86131b12970c773ece822e4a51542841f08926b9cc155a4f706fd4b` |
| VIX v3 aggressive | `30689825451` | `8815264414` | `sha256:d6397090d7c8a01bf7c383df849f72ff25c2ad6247b0644522f0f25d022427fb` |
| Breadth / VXN v4 | `30690518926` | `8815500542` | `sha256:74cef0df0e77f5391721946c567997843a35b0920e66573bb03e267e71ac42ac` |
| VXN leverage veto v4.1 | `30690786777` | `8815588121` | `sha256:6184c8e2f4186d4fc90848cb4ceb974c7334d9fce56b9e17eda1ef1a07ce4cd4` |

Detailed reports remain under `docs/research/`. Machine-readable run records are written under `artifacts/strategy_runs/<experiment_id>/<run_id>/run_record.json` by `StrategyExperimentJournal` during evidence workflows.

## Current strategy interpretation

The leading architecture is:

1. **Price repair:** identifies recovery opportunity.
2. **VIX:** controls broad-market defense and the transition between QQQI and QQQ.
3. **VXN:** vetoes Nasdaq leverage when technology-specific implied volatility remains stressed.
4. **TQQQ weight:** determines participation magnitude after the recovery state is confirmed.

This is a risk-budget architecture, not a next-day directional forecast.

## Frozen monitoring candidate

Candidate ID: `qqqi_qqq_tqqq_vxn_leverage_v4_1`

Monitoring start: 2026-08-01

Status:

- `research_only=true`
- `trade_ready=false`
- `post_result_hypothesis=true`
- `candidate_for_out_of_sample_monitoring=true`

Do not change the following while accumulating prospective evidence:

- VIX stress, easing or normalization thresholds;
- VXN stress definition;
- price-repair thresholds;
- 75% TQQQ weight;
- next-open execution convention;
- transaction-cost assumption.

## Next admissible research sequence

### 1. Long-history validation of the attack layer

Before adding another factor, isolate the QQQ/TQQQ risk-allocation layer and replay the frozen VIX v3 and VXN-veto rules over the longest reliable common QQQ, TQQQ, VIX and VXN history.

This study must not claim historical QQQI performance. Its purpose is narrower: determine whether the leverage timing and VXN veto remain useful through multiple stress regimes, including 2018, 2020 and 2022.

Required comparisons:

- QQQ buy and hold;
- static 25% QQQ / 75% TQQQ;
- frozen VIX v3 attack layer;
- frozen VIX v3 + VXN leverage veto;
- rolling and regime-specific attribution;
- blocked-entry and false-start diagnostics.

### 2. Churn and dwell-time diagnostics

Measure whether v4.1 generates avoidable re-entry churn without changing the strategy. Report:

- state dwell times;
- round trips within 5, 10 and 20 sessions;
- cost contribution by exit reason;
- returns immediately after VXN veto exits;
- missed recovery returns after blocked entries.

Only after diagnostics may one separately version a hysteresis or cooldown hypothesis. No grid search is allowed.

### 3. Orthogonal single-factor challengers

Test one factor at a time and preserve the v4.1 architecture:

- **absolute breadth:** QQQE's own trend, not QQQE relative outperformance versus QQQ; use as a soft leverage tier rather than a binary hard gate;
- **realized downside volatility:** use only as a leveraged-state veto or risk-scaling input;
- **credit-risk proxy:** test a liquid, reproducible credit-spread proxy only after data-quality validation.

A new factor should be rejected if it merely duplicates VIX/VXN information, improves only one late episode, increases turnover without improving risk-adjusted return, or changes the QQQI defensive trace without an explicit hypothesis.

### 4. Combination rule

Do not combine new factors until each has demonstrated independent incremental value under the same execution and cost assumptions. Combination tests must preserve a reserved evaluation window and report marginal contribution relative to v4.1.

## Promotion criteria

No strategy should be marked trade ready until all of the following are satisfied:

- prospective out-of-sample evidence exists after 2026-08-01;
- attack-layer rules survive long-history multi-regime validation;
- performance is not dominated by one or two episodes;
- turnover and slippage sensitivity remain acceptable;
- each active factor has an explainable and independently measured role;
- the final contract, evidence hashes and decision are recorded in the journal and this ledger.
