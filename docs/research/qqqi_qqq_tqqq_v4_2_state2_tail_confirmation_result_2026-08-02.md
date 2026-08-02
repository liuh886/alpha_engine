# QQQI / QQQ / TQQQ v4.2 state-2 tail and confirmation research result

**Evidence date:** 2026-08-02  
**Economic sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Current baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Official cost:** 10 basis points per turnover unit  
**Status:** research-only; not trade-ready

## Executive decision

1. Keep v4.2 unchanged as the current research baseline.
2. Reject a continuous close-based state-2 volatility-budget challenger under the pre-registered gate.
3. Reject one-session confirmation on the `0→1` bridge entry.
4. Do not promote one-session confirmation on the `1→2` leverage entry despite attractive full-sample metrics.
5. Reject the combined risk-increase confirmation as a new candidate because it fails the chronological and event-consistency gates.
6. Treat the mechanically delayed execution result as a robustness warning, not an optimization result.
7. Stop retrospective confirmation, persistence, threshold and fixed-weight searches on this sample.

The central finding is that v4.2's worst leveraged losses are usually realized during the trading session, while the frozen daily indicators show no warning at the preceding close. A close-based dynamic risk budget therefore cannot reliably avoid the principal tail event without adding a new intraday data and execution regime.

## 1. State-2 tail-event decomposition

The formal sample contains 12 contiguous state-2 episodes and 129 leveraged sessions.

| Metric | Result |
|---|---:|
| State-2 episodes | 12 |
| State-2 sessions | 129 |
| Mean episode net return | 4.71% |
| Negative episode rate | 41.67% |
| Mean episode maximum drawdown | -4.81% |
| Worst episode net return | -7.85% |
| Abrupt or gap-dominated episodes | 66.67% |
| Mean overnight share of episode losses | 26.62% |
| Warning observable at prior close | 0.00% |
| Same-close exit signal on worst day | 75.00% |

### Worst state-2 sessions

| Date | Net return | Intraday contribution | Overnight contribution | Prior-close warning | Same-close exit |
|---|---:|---:|---:|---|---|
| 2024-09-03 | -7.85% | -6.08% | -1.63% | No | Yes |
| 2025-07-31 | -6.72% | -4.06% | -2.66% | No | No |
| 2024-12-18 | -6.69% | -8.70% | 2.00% | No | Yes |
| 2026-06-05 | -4.75% | -8.69% | 3.94% | No | Yes |
| 2024-11-14 | -4.41% | -1.56% | -2.85% | No | No |
| 2026-06-03 | -4.00% | -1.06% | -2.94% | No | No |
| 2024-10-01 | -3.77% | -3.30% | -0.47% | No | Yes |
| 2025-05-22 | -3.74% | 0.16% | -3.90% | No | No |
| 2024-08-22 | -3.18% | -5.13% | 2.10% | No | Yes |
| 2024-08-26 | -3.16% | -2.15% | -0.87% | No | Yes |

Across the ten worst leveraged sessions, only 27.33% of negative contribution came from the close-to-next-open interval. None had a warning observable at the preceding close, although 60.00% generated an exit signal at the close of the loss day.

This distinction is decisive:

- the model often recognizes deterioration by the loss-day close;
- the open-to-open backtest executes that decision only at the next open;
- most damage has already occurred before that close;
- scaling TQQQ from the same close-derived indicators cannot be credited with avoiding the loss already realized intraday.

The pre-registered continuous-volatility-budget gate therefore failed on warning observability and episode gradualness. No such challenger is authorized.

## 2. Execution robustness

The corrected timing study separates a true mechanical delay from confirmation. The official baseline remains next-open execution with 10 bps cost.

| Scenario | CAGR | Sharpe | Sortino | Max drawdown | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|
| Current v4.2 | 33.06% | 1.244 | 1.801 | -24.21% | 1.365 | 55.0 |
| Mechanical one-session delay | 33.35% | 1.266 | 1.846 | -27.15% | 1.228 | 54.0 |
| +5 bps stress | 31.59% | 1.200 | 1.735 | -24.73% | 1.278 | 55.0 |
| +10 bps stress | 30.14% | 1.157 | 1.668 | -25.86% | 1.166 | 55.0 |
| +20 bps stress | 27.29% | 1.069 | 1.536 | -28.07% | 0.972 | 55.0 |

The mechanical one-session delay raises full-sample CAGR by only 0.29 percentage points, while maximum drawdown worsens by 2.94 percentage points. It improves the early segment but reduces late-segment CAGR from 46.68% to 45.18%. This is not a robust execution improvement.

Additional cost stress confirms that the strategy remains economically positive but is meaningfully sensitive to friction:

- +5 bps beyond the official assumption lowers CAGR by 1.46 percentage points;
- +10 bps lowers CAGR by 2.91 percentage points;
- +20 bps lowers CAGR by 5.77 percentage points and worsens maximum drawdown to -28.07%.

## 3. Confirmation ablation

### Full-sample results

| Scenario | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| Current v4.2 | 33.06% | 25.62% | 1.244 | 1.801 | -24.21% | 1.365 | 55.0 |
| Confirm `0→1` bridge entry | 32.47% | 25.59% | 1.228 | 1.776 | -24.23% | 1.340 | 54.0 |
| Confirm `1→2` leverage entry | 35.64% | 24.80% | 1.354 | 1.998 | -24.21% | 1.472 | 37.5 |
| Confirm both risk increases | 35.00% | 24.76% | 1.336 | 1.969 | -24.23% | 1.445 | 37.0 |
| Confirm all transitions | 35.70% | 25.11% | 1.342 | 1.969 | -27.15% | 1.315 | 34.0 |

### Bridge-entry confirmation — reject

Requiring the `0→1` decision to persist one more session lowers CAGR from 33.06% to 32.47%. Across 10 affected events, 60% are positive, but the arithmetic total effect is negative. The bridge is already the deliberately cautious allocation for uncertain recovery; adding another confirmation day delays useful exposure without improving drawdown.

### Leverage-entry confirmation — attractive but not robust enough

Confirming only the `1→2` leverage entry produces the strongest full-sample headline result:

- CAGR: 35.64%;
- Sharpe: 1.354;
- Sortino: 1.998;
- maximum drawdown: -24.21%, effectively unchanged;
- turnover: 37.5, down from 55.0.

However, the improvement does not meet the evidence standard:

- only 41.67% of 12 affected entries improve;
- the early-segment CAGR rises from 24.68% to 29.17%;
- the late-segment CAGR falls from 46.68% to 45.96%;
- the largest positive event is the avoided 2024-09-03 leveraged session, creating material episode concentration.

The result is therefore a plausible post-result hypothesis, not a stable candidate.

### Combined risk-increase confirmation — reject

Confirming both `0→1` and `1→2` transitions improves full-sample CAGR to 35.00%, Sharpe to 1.336, and reduces turnover to 37.0. It nevertheless fails the pre-registered gate:

- positive event rate: 50.00%, below the 60% minimum;
- early-segment CAGR delta: +3.87 percentage points;
- late-segment CAGR delta: -1.39 percentage points;
- top positive event share: 42.56%;
- direct promotion is explicitly prohibited.

The chronological failure and 50% event win rate outweigh the attractive headline metrics.

## 4. Methodology correction

The first state-2 diagnostic implementation used labels such as `risk_increase_delay_1` for a mechanism that actually required a target state to persist for an additional session. That mechanism is confirmation, not a mechanical execution delay.

The accepted evidence separates them:

- `fixed_execution_delay_1`: unconditional extra execution latency;
- `bridge_entry_confirmation_1`: persistence on `0→1`;
- `leverage_entry_confirmation_1`: persistence on `1→2`;
- `risk_increase_confirmation_1`: persistence on both risk-increasing transitions.

No strategic decision relies on the ambiguous initial labels.

## 5. Final research decision

### Retained

- v4.2 remains the current research baseline;
- v4.1 remains the immutable historical signal comparator;
- the blended QQQI/SGOV structure remains a separate drawdown-focused challenger;
- daily decision alerts continue to use v4.2 only.

### Rejected or not authorized

- continuous daily-close state-2 volatility scaling;
- bridge-entry confirmation;
- leverage-entry confirmation as a promoted or prospectively monitored challenger;
- combined risk-increase confirmation;
- all-transition confirmation;
- further persistence-length, threshold, bridge-weight, SGOV-weight or TQQQ-weight searches on the current sample.

### Next admissible work

1. Continue v4.2 prospective monitoring from 2026-08-01.
2. Measure real alert delivery, data freshness and execution observations.
3. Treat intraday tail control as a separate strategy family requiring governed intraday data and a different execution contract; do not retrofit it into v4.2 from daily bars.
4. Revisit confirmation only if new prospective events independently support it, not through additional retrospective parameter search.
5. For a lower-risk allocation today, evaluate the already-defined blended QQQI/SGOV profile rather than altering v4.2's state-2 logic.

## 6. Evidence

- workflow run: `30733002466`;
- artifact ID: `8828582862`;
- artifact digest: `sha256:11f7803e47b13d6700a73303b61915f814efaaa97cc4240fabde7288e5cb25e0`;
- state-2 notebook: `notebooks/19_qqqi_qqq_tqqq_v4_2_state2_tail_diagnostics.ipynb`;
- confirmation notebook: `notebooks/20_qqqi_qqq_tqqq_v4_2_risk_confirmation_ablation.ipynb`.

The evidence bundle contains governed data identity, episode-level CSVs, tail-day decomposition, execution and confirmation tables, machine-readable summaries, and executed notebooks.
