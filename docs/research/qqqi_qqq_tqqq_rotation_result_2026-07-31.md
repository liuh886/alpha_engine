# QQQI / QQQ / TQQQ Rotation: Live-Data Result

## Status

- Experiment: `qqqi_qqq_tqqq_rotation_v1`
- Evidence cutoff requested: 2026-08-01
- Latest completed market session: 2026-07-31
- Economic return sample: 2024-01-30 through 2026-07-30, 627 open-to-open observations
- Multi-stage recovery evidence run: `30686827663`
- Evidence artifact digest: `sha256:056fe9eb49c6d8d632d40d396131a97300dd8f7facbe680bcb33f9fcba1f117b`
- Boundary: `research_only=true`, `trade_ready=false`

QQQI was launched on 2024-01-29, so the true three-asset common sample cannot directly cover the 2020 pandemic shock or the 2022 technology bear market. Earlier QQQ/TQQQ results in this report are context only, not a synthetic QQQI backfill.

## Executive conclusion

The experiment does **not** support the current three-state strategy as an improvement over buy-and-hold QQQ.

1. QQQI was generally smoother than QQQ in weak, sideways and transition regimes, but usually earned a lower cumulative return.
2. QQQ's recovery advantage is **stage-dependent**. MA200 reclaim is too late and too sparse to be the sole recovery definition. Early 5-day breakout and intermediate MA50 reclaim produced more usable and more discriminating evidence.
3. Rotation A reduced QQQ's maximum drawdown by only 0.49 percentage points while giving up 1.62 percentage points of CAGR. Its Sharpe and Calmar were also lower than QQQ.
4. Rotation B was identical to Rotation A because the TQQQ state was never reached.
5. The 324-combination grid looked numerically insensitive, but this was not genuine robustness: `drawdown_threshold` and `n_exit_short` never changed any outcome because TQQQ exposure was zero in every combination.

The correct decision is therefore:

- **QQQI defensive premise: partially supported.**
- **QQQ recovery premise: conditionally supported, strongest after intermediate confirmation rather than MA200 alone.**
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

## How should recovery speed be measured?

MA200 reclaim is only a late trend-confirmation event. It does not capture the earlier part of a rebound, and it can still produce false starts. The revised study therefore defines one material-drawdown episode whenever QQQ reaches at least a 10% drawdown, retains that shock in memory for 63 sessions, and records the first occurrence of each recovery stage:

1. `breakout_5d`: first close above the prior five-session high;
2. `ma20_reclaim`: first reclaim of MA20 / Bollinger middle band;
3. `ma50_reclaim`: first reclaim of MA50;
4. `breakout_20d`: first close above the prior 20-session high;
5. `ma200_reclaim`: first reclaim of MA200.

There is at most one trigger of each family in each shock episode. A signal is confirmed at close `t`, and all return and time-to-target measurements start at open `t+1`.

The common sample contained three independent shock episodes and fourteen stage events.

### Recovery-stage summary

| Trigger family | Median sessions after shock | QQQ wins, 5d | QQQ wins, 20d | QQQ wins, 40d | Median QQQ advantage, 40d |
|---|---:|---:|---:|---:|---:|
| 5-day breakout | 5 | 3/3 | 1/3 | 3/3 | +2.05 pp |
| MA20 reclaim | 7 | 2/3 | 1/3 | 3/3 | +1.68 pp |
| MA50 reclaim | 9 | 3/3 | 2/3 | 3/3 | +3.63 pp |
| 20-day breakout | 13 | 2/3 | 2/3 | 2/3 | +3.63 pp |
| MA200 reclaim | 9 | 1/2 | 1/2 | 2/2 | +4.65 pp |

The MA200 median timing is not later in this tiny sample because only two MA200 events were observed; it is therefore not a reliable stage-order estimate.

### Direct speed metrics

| Trigger family | QQQ +5% hit rate | QQQI +5% hit rate | Median days to +5%, QQQ | Median days to +5%, QQQI |
|---|---:|---:|---:|---:|
| 5-day breakout | 100% | 100% | 6.0 | 7.0 |
| MA20 reclaim | 100% | 67% | 30.0 | 18.0 |
| MA50 reclaim | 100% | 67% | 8.0 | 14.0 |
| 20-day breakout | 67% | 67% | 6.5 | 15.5 |
| MA200 reclaim | 100% | 50% | 20.5 | 11.0 |

These results change the interpretation:

- **5-day breakout identifies the earliest opportunity.** QQQ beat QQQI over the first five sessions in all three episodes and reached +5% slightly faster. It is useful for moving from defense to ordinary QQQ, but it is too early to justify full leverage.
- **MA20 reclaim is noisy.** The March 2025 signal was followed by another decline; QQQ lost 10.83% over the next ten sessions versus 9.89% for QQQI. MA20 alone should not start TQQQ.
- **MA50 reclaim is the strongest current candidate for intermediate confirmation.** QQQ beat QQQI over five sessions in all three episodes, over 10 and 20 sessions in two of three, and over 40 sessions in all three. QQQ reached +5% in a median eight sessions versus fourteen for QQQI.
- **20-day breakout is useful confirmation but can be late.** The August 2024 event entered immediately before a renewed short-term decline.
- **MA200 reclaim is sparse and can still false-trigger.** The March 2025 event was followed by a 15.59% QQQ loss over ten sessions. It should remain a long-trend reference or defensive boundary, not the sole recovery clock.

The sample remains only three shock episodes. These findings identify candidate mechanisms; they do not validate a production entry rule.

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

Do not select one of the observed triggers merely because it looks best in three episodes. Freeze a new `v2` mechanism before evaluating portfolio returns.

The most defensible staged hypothesis is:

1. **Shock memory:** QQQ experienced at least a 10% drawdown during the previous 63 sessions.
2. **Defense to QQQ:** move from QQQI to QQQ after a 5-day breakout or MA20 reclaim. This captures the early repair without applying leverage.
3. **QQQ to partial TQQQ:** permit a 30%–50% TQQQ sleeve only after MA50 reclaim, preferably with either a 20-day breakout or a positive MA20 slope as secondary confirmation.
4. **Do not require current deep drawdown:** the historical shock and current recovery confirmation are separate conditions.
5. **Fast degradation:** remove TQQQ on a confirmed MA20 break; move fully to QQQI when the long-trend defensive boundary is broken.
6. **MA200's role:** use MA200 primarily as a long-horizon risk boundary or late confirmation, not as the only definition of recovery.

This staged design matches the empirical pattern better than the current rule:

- very early signals can justify leaving QQQI;
- MA20 alone is too noisy for leverage;
- MA50 appears to be a more credible leverage gate;
- MA200 alone sacrifices earlier opportunity and does not eliminate false starts.

Version A should remain the simple benchmark. The next frozen challenger must be compared against QQQ, QQQI and Rotation A, and must pass state-reachability, parameter-activity and tail-risk checks before any performance conclusion is accepted.
