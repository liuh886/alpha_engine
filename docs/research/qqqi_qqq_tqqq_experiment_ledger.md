# QQQI / QQQ / TQQQ Strategy Experiment Ledger

Last updated: 2026-08-02

## Purpose

This ledger is the durable decision record for the QQQI / QQQ / TQQQ rotation research line. It complements versioned contracts, result reports, notebooks, evidence archives and `StrategyExperimentJournal` records.

A strong retrospective metric is not sufficient for a trade-ready designation. A research baseline may nevertheless change when a simpler executable architecture improves net results under the same signal trace and cost convention.

## Shared research boundary

Unless a contract states otherwise:

- core tradable instruments: QQQI, QQQ and TQQQ;
- defensive-asset research may add SGOV without changing the signal trace;
- signal generation: session close;
- execution: next session adjusted open;
- return measurement: adjusted open to adjusted open;
- transaction cost: 10 basis points per turnover unit;
- formal three-asset and SGOV comparison sample: 2024-01-30 through 2026-07-30;
- observations: 627;
- no pre-inception backfill for QQQI or SGOV;
- all strategies remain `research_only=true` and `trade_ready=false`.

The short QQQI history remains the principal evidence limitation.

## Experiment lineage

| Version or study | PR | Primary change | Decision |
|---|---:|---|---|
| Price-only v1 | #261 | Initial MA200-oriented rotation | Reject as primary architecture; recovery clock was too slow |
| Price-repair v2 / VIX v2 | #261 | Multi-stage repair and 50% TQQQ; VIX risk budget | Retain architecture; price repair is the return engine |
| VIX v3 aggressive | #262 | Increase partial leverage from 50% to 75% TQQQ | Retain; do not search leverage weight further |
| Breadth / VXN v4 | #265 | Relative breadth, VXN replacement and dual confirmation | Reject relative breadth hard gate; retain VXN information |
| VXN leverage veto v4.1 | #266 | VXN only vetoes the 75% TQQQ layer | Retain as immutable historical signal comparator |
| Long-history attack layer | #272 | Replay frozen VIX/VXN leverage logic from 2010 | Directionally positive but not stable enough for promotion |
| Churn diagnostics | #274 | Diagnose VXN exits and rapid re-entry | Identified short exits; no rule change by itself |
| Two-day VXN persistence | #276 | Require two pressure days before exiting leverage | Reject; turnover fell but all risk-adjusted metrics worsened |
| Absolute breadth soft tier | #278 | Use QQQE absolute trend to scale leverage | Reject; lower exposure did not improve risk budgeting |
| QQQ downside-volatility veto | #279 | Veto leverage on realized downside stress | Reject; duplicated VXN and blocked profitable entries |
| HYG/SHY credit proxy | #280 | Credit-risk appetite veto | Positive full sample but concentrated in 2015; do not add |
| Prospective v4.1 monitor | #281 | Frozen monitoring from 2026-08-01 | Retain as historical comparison stream |
| Confidence bridge v4.2 | #297 | State 1 becomes 50% QQQI / 50% QQQ; state trace unchanged | Retained as monitoring challenger |
| **v4.2 baseline promotion** | **#327** | **Use lower turnover and improved net metrics as the default research architecture** | **Current research baseline from 2026-08-02; still not trade-ready** |
| State-1 lifecycle and tail diagnostics | #327 | Actual holding-cycle attribution and deeper drawdown metrics | Completed; confirms asymmetric bridge value |
| Pure SGOV defense | #327 | Replace QQQI reserve with SGOV in states 0 and 1 | Reject as primary architecture |
| **Blended QQQI / SGOV defense** | **#327** | **Split defensive reserve between QQQI and SGOV** | **Retain as drawdown-focused challenger; no baseline replacement** |
| v4.2 signal alerts | #327 / #335 | Daily next-open decision card with Issue and Telegram delivery | Retain; no order placement |
| **State-2 tail decomposition** | **#339** | **Separate intraday and overnight loss contribution and test close-based observability** | **Continuous close-based volatility scaling rejected; v4.2 unchanged** |
| Bridge-entry confirmation | #339 | Require `0→1` to persist one additional session | Reject; lower full-sample CAGR and no drawdown benefit |
| Leverage-entry confirmation | #339 | Require `1→2` to persist one additional session | Attractive headline metrics but not promoted; low event win rate and weaker late sample |
| Combined risk-increase confirmation | #339 | Confirm both `0→1` and `1→2` | Reject; fails chronological and event-consistency gates |

## Current complete result summary

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Total return | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 22.01% | 21.30% | 1.041 | 1.489 | -24.17% | 0.911 | 64.05% | — |
| VIX v3, 75% TQQQ | 29.62% | 26.63% | 1.108 | — | -24.43% | 1.212 | 90.68% | 65 |
| Historical v4.1 VXN leverage veto | 32.42% | 25.82% | 1.218 | 1.763 | -24.45% | 1.326 | 101.11% | 71 |
| **Current v4.2 50/50 bridge baseline** | **33.06%** | **25.62%** | **1.244** | **1.801** | **-24.21%** | **1.365** | **103.53%** | **55** |
| Pure SGOV defense | 25.05% | 17.15% | 1.390 | 2.012 | -21.03% | 1.191 | 74.39% | 55 |
| Blended QQQI / SGOV defense | 29.54% | 19.75% | **1.410** | **2.042** | **-17.91%** | **1.649** | 90.39% | 55 |

Confirmation studies below are rejected diagnostics, not active strategies:

| Diagnostic | CAGR | Sharpe | Sortino | Max drawdown | Calmar | Turnover | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| Mechanical one-session delay | 33.35% | 1.266 | 1.846 | -27.15% | 1.228 | 54.0 | Not robust |
| Confirm `0→1` | 32.47% | 1.228 | 1.776 | -24.23% | 1.340 | 54.0 | Reject |
| Confirm `1→2` | 35.64% | 1.354 | 1.998 | -24.21% | 1.472 | 37.5 | Do not promote |
| Confirm both risk increases | 35.00% | 1.336 | 1.969 | -24.23% | 1.445 | 37.0 | Reject |

## Architecture findings

### Price repair, VIX and VXN

1. QQQ drawdown provides shock memory.
2. Short- and medium-horizon price repair identifies recovery opportunity.
3. VIX regulates broad-market defense and initial risk budget.
4. VXN is useful only as a Nasdaq-specific veto for the 75% TQQQ layer.
5. MA200 remains a long-term defensive boundary rather than the primary recovery clock.

### TQQQ leverage layer

The state-1-to-state-2 transition remains the strongest measured signal component. Twelve add-leverage events produced about +5.76 percentage points mean twenty-session benefit and approximately 91.7% positive relative outcomes in the original event study.

The state-2 tail study adds an important limitation: the ten worst leveraged sessions had no warning observable at the preceding close. Sixty percent generated an exit signal only at the close of the loss day, after most damage had occurred intraday. Daily close-derived scaling cannot be credited with avoiding losses already realized before the close.

No new TQQQ threshold or weight search is authorized.

### v4.2 confidence bridge

v4.2 changes no signal date:

- state 0: 100% QQQI;
- state 1: 50% QQQI + 50% QQQ;
- state 2: 25% QQQ + 75% TQQQ.

Relative to v4.1 it improves net results and reduces turnover from 71 to 55 units under the same 10 bps cost convention. The post-result origin remains part of the evidence record.

Decision on 2026-08-02: v4.2 remains the current research baseline. v4.1 remains the immutable historical signal comparator.

## State-1 lifecycle attribution

Eighteen actual state-1 intervals were observed.

| Lifecycle | Episodes | Mean v4.2 minus v4.1 net return | Positive delta rate | Mean drawdown improvement | Interpretation |
|---|---:|---:|---:|---:|---|
| `0->1->0` | 5 | **+0.275 pp** | **80.0%** | **+0.417 pp** | Bridge is valuable when recovery attempts fail |
| `0->1->2` | 5 | -0.257 pp | 20.0% | +0.019 pp | Bridge gives up some upside in fast successful recoveries |
| `2->1->2` | 7 | **+0.057 pp** | 57.1% | **+0.154 pp** | Slight benefit during temporary deleveraging |
| `2->1->0` | 1 | -0.045 pp | 0.0% | **+0.256 pp** | Approximately return-neutral with better path risk |

The bridge is therefore an asymmetric risk-budget improvement rather than a stronger predictor.

## State-2 tail and confirmation decision

The formal sample contains 12 state-2 episodes and 129 leveraged sessions.

- worst episode net return: -7.85%;
- negative episode rate: 41.67%;
- 66.67% of episodes are abrupt or gap-dominated under the frozen classification;
- only 27.33% of negative contribution across the ten worst sessions was overnight;
- prior-close warning rate for those sessions was 0%;
- same-close exit signal rate was 60%.

The continuous close-based volatility-budget gate failed. Intraday tail control would require governed intraday data and a separate execution contract; it is not an admissible v4.2 patch.

The confirmation ablation separated true mechanical latency from persistence:

- mechanical one-session latency slightly raised full-sample CAGR but worsened maximum drawdown by 2.94 percentage points and weakened the late sample;
- confirming `0→1` reduced CAGR;
- confirming `1→2` improved headline metrics but only 5 of 12 affected entries won and late-segment CAGR was 0.72 percentage points below v4.2;
- confirming both risk increases had a 50% event win rate and a -1.39 percentage-point late-segment CAGR delta.

Decision: reject all confirmation challengers and stop retrospective confirmation-length searches on this sample.

## SGOV defensive architecture

### Pure SGOV defense — rejected

Pure SGOV lowers volatility and expected shortfall but gives up too much return participation:

- CAGR falls from 33.06% to 25.05%;
- total return falls from 103.52% to 74.39%;
- Calmar falls from 1.365 to 1.191;
- longest underwater run increases from 113 to 207 sessions;
- ulcer index worsens.

It is not retained as the primary architecture.

### Blended QQQI / SGOV defense — retained challenger

The blended structure uses:

- state 0: 50% QQQI / 50% SGOV;
- state 1: 25% QQQI / 25% SGOV / 50% QQQ;
- state 2: unchanged 25% QQQ / 75% TQQQ.

It produces:

- maximum drawdown improvement from -24.22% to -17.91%;
- expected shortfall improvement from -3.93% to -3.05%;
- volatility reduction from 25.62% to 19.75%;
- Sharpe improvement from 1.244 to 1.410;
- Sortino improvement from 1.801 to 2.042;
- Calmar improvement from 1.365 to 1.649;
- CAGR reduction from 33.06% to 29.54%;
- longest underwater run increase from 113 to 195 sessions.

Decision: retain as a drawdown-focused challenger. It reduces loss depth but delays recovery to the prior peak. Do not replace v4.2 and do not test additional SGOV weights.

## Signal-alert architecture

The alert layer reads the existing v4.2 prospective-monitor summary and never recreates the state machine independently.

A fresh state-change decision card contains:

- governed data date and signal freshness;
- close signal date and intended next-session-open execution;
- current-state duration;
- explicit QQQI/QQQ/TQQQ buy and sell weight changes;
- turnover and model-cost estimate;
- QQQ position relative to MA20, MA50 and MA200;
- VIX/VXN values and dynamic thresholds;
- transition-specific historical evidence, confirmation path, invalidation and principal risk;
- deterministic fingerprint and research-only disclaimer.

The canonical durable channel is an owner-assigned GitHub Issue. Telegram is the immediate delivery channel. The workflow never places orders.

## Evidence references

| Study | Workflow run | Artifact ID | Evidence digest |
|---|---:|---:|---|
| VIX v3 aggressive | `30689825451` | `8815264414` | `sha256:d6397090d7c8a01bf7c383df849f72ff25c2ad6247b0644522f0f25d022427fb` |
| Breadth / VXN v4 | `30690518926` | `8815500542` | `sha256:74cef0df0e77f5391721946c567997843a35b0920e66573bb03e267e71ac42ac` |
| VXN leverage veto v4.1 | `30690786777` | `8815588121` | `sha256:6184c8e2f4186d4fc90848cb4ceb974c7334d9fce56b9e17eda1ef1a07ce4cd4` |
| Long-history attack layer | `30691947502` | `8815971914` | `sha256:64cb61754392e2c195ebceb5eba46d69cf776ef16abf0b8800f91c5926da973f` |
| Initial prospective monitor | `30694181701` | `8816681833` | `sha256:4e6b27f6910bc630c976d633f8927566789d50f3f417596c0256b6803dcc08a7` |
| v4.2 bridge result | `30706201043` | `8820398584` | `sha256:3b4962b11796ee72ec4f74cca12ddf0d40800cf5417af4e42dabfb3a3d81abbf` |
| v4.2 lifecycle, tail and corrected SGOV suite | `30730596122` | `8827843430` | `sha256:7a5feaa66b4d830969b5d1ffa3aef21ca1b98f6157be3af7062b40304c6c79e4` |
| v4.2 signal-alert validation | `30730596133` | `8827841085` | `sha256:2fec875e52d655dad94640f3a4fa8b622c1c3e8eb0f71ef4bcdc904fb4506d1a` |
| **State-2 tail and confirmation ablation** | **`30733002466`** | **`8828582862`** | **`sha256:11f7803e47b13d6700a73303b61915f814efaaa97cc4240fabde7288e5cb25e0`** |

The initial SGOV run with an economic start of 2024-10-16 was discarded because the signal history lacked sufficient warmup. The initial state-2 exploratory `delay` labels were also superseded because they implemented confirmation rather than mechanical latency. No decision uses either invalid evidence path.

## Current baseline and active challengers

### Current research baseline

`qqqi_qqq_tqqq_vxn_bridge_v4_2`

- effective date: 2026-08-02;
- active signal-alert source;
- `research_only=true`;
- `trade_ready=false`;
- `post_result_hypothesis=true` retained;
- cost remains 10 bps per turnover unit.

### Historical signal comparator

`qqqi_qqq_tqqq_vxn_leverage_v4_1`

- exact same state dates as v4.2;
- preserved for lineage and attribution;
- no longer the primary comparator for new portfolio challengers.

### Drawdown-focused challenger

`qqqi_sgov_blended_defense`

- exact v4.2 signal trace and state-2 allocation;
- lower drawdown depth and expected shortfall;
- lower CAGR and longer underwater duration;
- retained for further controlled research only.

No confirmation or state-2 volatility-budget challenger is active.

## Next admissible work

1. Continue frozen v4.2 versus v4.1 prospective monitoring from 2026-08-01.
2. Run the daily v4.2 signal-alert workflow and record real delivery, data freshness and execution deviations.
3. Do not continue retrospective confirmation, persistence, threshold, bridge-weight, SGOV-weight or TQQQ-weight searches on this sample.
4. Treat intraday tail control as a separate strategy family requiring governed intraday data and a different execution contract.
5. Revisit confirmation only if future prospective events independently support it.
6. Use the already-defined blended QQQI/SGOV profile when a lower-risk allocation is desired; do not modify v4.2 under that objective.

## Trade-ready criteria

No strategy should be marked trade ready until:

- meaningful prospective out-of-sample evidence exists after 2026-08-01;
- performance is not dominated by one or two episodes;
- turnover and execution assumptions remain acceptable;
- drawdown depth and duration are both assessed;
- data sources and adjusted-return treatment are governed;
- the active architecture remains explainable and simple;
- contracts, evidence hashes, notebooks and decisions are synchronized.
