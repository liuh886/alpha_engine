# QQQI / QQQ / TQQQ sequential factor-cycle decision

Date: 2026-08-01

## Final decision

Keep the frozen v4.1 strategy unchanged.

No factor or state-machine modification tested after v4.1 met the standard for clear, stable, independently attributable improvement. The research cycle therefore ends without adding breadth, realized downside volatility, credit, cooldown or VXN-persistence logic.

Current architecture:

1. QQQ price repair identifies the recovery opportunity.
2. VIX controls broad-market defense and the transition between QQQI and QQQ.
3. VXN only vetoes the 75% TQQQ layer when Nasdaq-specific implied volatility remains stressed.
4. The leveraged state remains 25% QQQ / 75% TQQQ.
5. Signals are decided at the close and executed at the next adjusted open with 10 bps cost per turnover unit.

Status:

- `research_only=true`;
- `trade_ready=false`;
- `candidate_for_out_of_sample_monitoring=true`;
- prospective monitoring start: `2026-08-01`.

## Sequential results

| Step | PR | Question | Result | Strategy action |
|---|---:|---|---|---|
| Long-history attack-layer validation | #272 | Does the v4.1 VXN veto remain useful across 2010-2026? | Directionally positive, but sparse and rolling stability insufficient | Retain VXN for prospective monitoring only |
| Churn and dwell diagnostics | #274 | Are VXN-only rapid exits recurring and costly? | Yes; rapid exits were harmful while longer exits were protective | Permit one predeclared persistence test |
| Two-close VXN exit persistence | #276 | Can one two-close rule reduce churn without harming performance? | Turnover fell, but CAGR, Sharpe, Sortino and Calmar deteriorated | Reject; stop cooldown/persistence optimization |
| QQQE absolute-breadth soft scaling | #278 | Can breadth scale 50%/75% TQQQ without a hard gate? | Lower volatility, but lower CAGR and risk-adjusted return with much higher turnover | Reject; no breadth factor added |
| QQQ realized downside-volatility veto | #279 | Does realized downside risk add value beyond VIX/VXN? | High VXN overlap; only nine holdings changed; portfolio weakened | Reject; no realized-volatility factor added |
| HYG/SHY credit-risk veto | #280 | Does credit-relative weakness add independent leverage information? | Positive full-sample result, but benefit concentrated in 2015 and absent after April 2023 | Record finding; do not add factor |

## Long-history v4.1 validation

Economic sample: 2010-10-18 through 2026-07-30.

| Attack layer | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| Frozen VIX v3 | 25.81% | 26.12% | 1.011 | 1.428 | -38.58% | 0.669 |
| Frozen v4.1 VXN veto | 26.31% | 25.78% | 1.036 | 1.472 | -38.58% | 0.682 |

The VXN rule changed economic holdings on only 21 of 3,969 sessions. Full-sample improvement came from a small number of avoided losses; most rolling windows actually affected by VXN did not outperform. This supports monitoring, not promotion.

## Rejected execution modification

The two-close VXN exit rule reduced turnover from 139 to 127 units, but reduced:

- CAGR from 26.31% to 25.97%;
- Sharpe from 1.036 to 1.019;
- Sortino from 1.472 to 1.444;
- Calmar from 0.682 to 0.673.

The result demonstrates that reducing churn is not automatically beneficial. Immediate VXN exits capture a few tail events that dominate the rule's value.

## Rejected independent factors

### QQQE absolute breadth

The soft 50%/75% schedule preserved the v4.1 decision trace but reduced CAGR from 25.92% to 24.48%, reduced Sharpe from 1.016 to 0.987 and increased turnover from 127 to 175 units. It reduced exposure during profitable recoveries.

### QQQ realized downside volatility

The factor overlapped VXN on 68.6% of its stress sessions and changed only nine economic holdings. It reduced CAGR, Sharpe, Sortino and Calmar without improving maximum drawdown or turnover. Most blocked entries preceded positive TQQQ returns.

### HYG/SHY credit risk

The data-quality gate passed, and the proxy contained substantial information distinct from VIX/VXN. Full-sample CAGR improved from 26.14% to 26.76% and Sharpe from 1.027 to 1.053 without extra turnover.

However:

- 2018-2021 was slightly weaker;
- 2022-2026 had slightly lower CAGR;
- the 2018 Q4, 2020 and 2022 windows were unchanged;
- 2015 contributed about +7.00 percentage points, more than the full +6.44-point changed-session benefit;
- excluding 2015, changed-session contribution was negative;
- no economic holding changed after April 2023.

Under the simplicity rule, a historically concentrated improvement is not sufficient for strategy inclusion.

## Evidence register

| Experiment | Workflow | Artifact | Digest |
|---|---:|---:|---|
| v4.1 long-history validation | `30691947502` | `8815971914` | `sha256:64cb61754392e2c195ebceb5eba46d69cf776ef16abf0b8800f91c5926da973f` |
| v4.1 churn diagnostics | `30692364844` | `8816103731` | `sha256:1ab6355419df866fbf656037a0ce065f00278f4060688415f5f43546763e444b` |
| two-close VXN persistence | `30692732090` | `8816230345` | `sha256:e0b5a7bc744d77ba96f465abcf4c34dd9dca5b8640d3ff42be7c7eb35f30b542` |
| absolute breadth soft scaling | `30693039261` | `8816336601` | `sha256:1bd7d594741073b0ea1baaa77eca1882207b1d094f1f8047feaf8eacc4265a7d` |
| downside-volatility veto | `30693357139` | `8816439747` | `sha256:f051722493f8f1e8ad7caca9c7016436bc85da6486110a8d3eed3ece8762a02e` |
| HYG/SHY credit-risk veto | `30693681032` | `8816539805` | `sha256:4ba588b36444ff841119b65eb3ebe9a735e80913b75720d163fb56a79a3e9907` |

Every experiment has a versioned contract, reproducible runner, tests, result report, evidence manifest and `StrategyExperimentJournal` record.

## Research boundary after this cycle

Retrospective factor expansion stops here.

The following are prohibited on the existing sample:

- alternative VIX or VXN thresholds;
- alternative VXN persistence or cooldown lengths;
- QQQE window or allocation searches;
- downside-volatility window or percentile searches;
- HYG/IEF, HYG/SHY window or momentum searches;
- multi-factor combinations;
- TQQQ weight optimization.

The next evidence must be generated prospectively by the unchanged v4.1 contract. Any future factor proposal requires a genuinely new economic hypothesis and a reserved evaluation period, not another transformation of the same historical observations.
