# QQQI / QQQ / TQQQ Rotation: Live-Data Result

## Status

- Experiment: `qqqi_qqq_tqqq_rotation_v1`
- Evidence cutoff requested: 2026-08-01
- Latest completed market session: 2026-07-31
- Economic return sample: 2024-01-30 through 2026-07-30, 627 open-to-open observations
- GitHub Actions run: `30683857956`
- Evidence artifact digest: `sha256:3d722b6d4d08707de5a5ec7f82d7b6c1c652034e1ff76bc0d4f1c4419e2a9389`
- Boundary: `research_only=true`, `trade_ready=false`

QQQI was launched on 2024-01-29, so the true three-asset common sample cannot directly cover the 2020 pandemic shock or the 2022 technology bear market. Earlier QQQ/TQQQ results in this report are context only, not a synthetic QQQI backfill.

## Executive conclusion

The experiment does **not** support the current three-state strategy as an improvement over buy-and-hold QQQ.

1. QQQI was generally smoother than QQQ in weak, sideways and transition regimes, but usually earned a lower cumulative return.
2. QQQ recovered faster than QQQI in two of the three complete MA200 recovery events, but three events are not enough to establish a reliable recovery advantage.
3. Rotation A reduced QQQ's maximum drawdown by only 0.49 percentage points while giving up 1.62 percentage points of CAGR. Its Sharpe and Calmar were also lower than QQQ.
4. Rotation B was identical to Rotation A because the TQQQ state was never reached.
5. The 324-combination grid looked numerically insensitive, but this was not genuine robustness: `drawdown_threshold` and `n_exit_short` never changed any outcome because TQQQ exposure was zero in every combination.

The correct decision is therefore:

- **QQQI defensive premise: partially supported.**
- **QQQ recovery premise: directionally supported but not established.**
- **Current QQQI / QQQ rotation: not superior to QQQ in the observed sample.**
- **Current three-state QQQI / QQQ / TQQQ strategy: structurally incomplete and not yet evaluated.**

## Common-window strategy comparison

| Strategy | Total return | CAGR | Volatility | Sharpe | Max drawdown | Calmar | Switches |
|---|---:|---:|---:|---:|---:|---:|---:|
| Buy & Hold QQQ | 64.06% | 22.01% | 21.30% | 1.041 | -24.17% | 0.911 | 0 |
| Buy & Hold QQQI | 52.18% | 18.38% | 19.77% | 0.953 | -21.53% | 0.854 | 0 |
| Buy & Hold TQQQ | 137.83% | 41.65% | 63.84% | 0.866 | -59.95% | 0.695 | 0 |
| Rotation A | 58.69% | 20.39% | 20.80% | 0.997 | -23.69% | 0.861 | 5 |
| Rotation B | 58.69% | 20.39% | 20.80% | 0.997 | -23.69% | 0.861 | 5 |

Relative to QQQ, Rotation B produced:

- CAGR: **-1.62 percentage points**
- annual volatility: **-0.51 percentage points**
- maximum drawdown improvement: **0.49 percentage points**
- Sharpe: **-0.044**
- Calmar: **-0.050**

The strategy switched only five times and held each state for an average of 104.5 sessions. Excessive turnover was therefore not the primary reason for underperformance. The larger issue was the state logic.

## Was QQQI more defensive?

All regime labels were determined from QQQ at close `t`; returns begin at the next executable open.

| QQQ-defined regime | Sessions | QQQI return | QQQ return | QQQI vol | QQQ vol | QQQI MDD | QQQ MDD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Below MA200 | 57 | 7.38% | 9.61% | 38.77% | 41.51% | -14.51% | -15.29% |
| Sideways above MA200 | 194 | 39.71% | 47.34% | 14.46% | 17.19% | -7.14% | -8.60% |
| Uptrend | 281 | 10.63% | 12.93% | 15.83% | 16.01% | -8.06% | -9.56% |
| Transition | 94 | -7.23% | -8.61% | 22.32% | 24.12% | -14.67% | -16.41% |

QQQI showed a consistent smoothing effect, especially in sideways and transition periods. That effect did not translate into a higher full-sample Sharpe or Calmar than QQQ, and it generally came with lower cumulative return.

## Did QQQ recover faster?

Only three complete MA200 recovery events existed in the common sample:

| Signal close | Next-open entry | QQQI 20-session return | QQQ 20-session return | QQQ minus QQQI |
|---|---|---:|---:|---:|
| 2025-03-25 | 2025-03-26 | -6.49% | -7.28% | -0.78 pp |
| 2025-05-12 | 2025-05-13 | 3.95% | 5.20% | 1.25 pp |
| 2026-04-08 | 2026-04-09 | 9.39% | 14.96% | 5.57 pp |

QQQ outperformed in two of three events, with an average advantage of 2.01 percentage points. This is useful directional evidence, but the event count is too small for a stable conclusion.

## Why Rotation B collapsed to Rotation A

Executed exposure was:

- QQQI: 60 sessions, 9.57%
- QQQ: 567 sessions, 90.43%
- TQQQ: 0 sessions, 0.00%

Signal audit in the common sample found:

- `enter_attack`: 335 sessions
- `enter_leveraged`: 0 sessions
- `defensive_break`: 46 sessions
- `exit_leveraged`: 164 sessions

The strategy requires both a confirmed trend recovery and a **current** drawdown of at least 8%, 10% or 15%. In this live period those conditions never overlapped. Consequently:

- every requested drawdown threshold produced zero TQQQ exposure;
- `drawdown_threshold` was inactive in all matched sensitivity groups;
- `n_exit_short` was also inactive because there was never a TQQQ position to exit;
- numerical stability across the grid cannot be interpreted as economic robustness.

This failure mode is now explicitly guarded by state-reachability and parameter-activity audits.

## Long-history context without inventing QQQI history

The frozen rules were also applied to QQQ's full signal history solely to check whether the state machine can request TQQQ in other market structures. This is a signal audit, not a three-asset return backtest.

| Scope | Defensive-state share | QQQ-state share | TQQQ-state share |
|---|---:|---:|---:|
| Full QQQ signal history | 17.00% | 79.42% | 3.58% |
| 2020 pandemic crash and recovery | 17.65% | 10.29% | 72.06% |
| 2022 rate-hike bear market | 94.82% | 5.18% | 0.00% |
| 2023–2024 AI bull market | 3.39% | 88.84% | 7.77% |
| QQQI live-history period | 9.38% | 90.62% | 0.00% |

This shows that the TQQQ branch is not universally impossible. It is unreachable in the short QQQI live sample, which means the current evidence cannot evaluate its realized contribution.

For risk context, TQQQ buy-and-hold experienced a -69.37% maximum drawdown during the selected 2020 crash/recovery window and a -80.77% maximum drawdown during 2022. Any future TQQQ state must therefore be evaluated for tail risk rather than judged by CAGR alone.

## Sensitivity and split validation

The frozen grid contained 324 combinations:

- MA length: 180 / 200 / 220
- buffer: 0% / 0.5% / 1% / 2%
- MA20 rise requirement: 3 / 5 / 7 sessions
- TQQQ drawdown threshold: 8% / 10% / 15%
- TQQQ exit persistence: 1 / 2 / 3 sessions

Observed grid dispersion was narrow:

- CAGR p10 / median / p90: 19.35% / 19.74% / 20.45%
- absolute MDD p10 / median / p90: 23.39% / 23.69% / 23.69%

However, structural governance changed the robustness decision:

- metric-dispersion heuristic: pass
- all intended states reached: no
- inactive parameters: `drawdown_threshold`, `n_exit_short`
- overall robustness: **fail**

The fixed default also passed the user's broad chronological split heuristics: late-sample CAGR was 19.00% versus 21.34% early, while late-sample MDD was -10.99% versus -23.69% early. This does not cure the short-history or dead-state problem.

## Recommended next experiment

Do not select a lower threshold merely because a post-hoc backtest looks attractive. Freeze a new `v2` hypothesis before evaluating returns.

The most defensible redesign is to separate the historical shock from current recovery confirmation:

1. **Shock memory:** QQQ experienced at least a 10% drawdown within a fixed recent window, such as the prior 20–60 sessions.
2. **Recovery confirmation:** QQQ is now above MA200 and MA20, with MA20 rising.
3. **TQQQ risk budget:** cap TQQQ at a partial allocation rather than 100% until the state has independent evidence.
4. **Fast degradation:** exit TQQQ on a confirmed MA20 break and fall directly to QQQI if MA200 is broken.

This better matches the stated economic idea: use leverage during recovery from a material drawdown, rather than requiring the market to remain deeply drawn down after trend recovery has already been confirmed.

Version A should remain the simple benchmark. The next frozen challenger should be compared against QQQ and Rotation A, with state reachability required before any performance conclusion is accepted.
