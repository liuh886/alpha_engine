# QQQI / QQQ / TQQQ Strategy Experiment Ledger

Last updated: 2026-08-01

## Purpose

This ledger is the durable decision record for the QQQI / QQQ / TQQQ rotation research line. It complements versioned YAML contracts, result reports, notebooks, evidence archives and `StrategyExperimentJournal` run records.

A strong retrospective metric is not sufficient for promotion.

## Shared research boundary

Unless a contract states otherwise:

- tradable instruments: QQQI, QQQ and TQQQ;
- signal generation: session close;
- execution: next session adjusted open;
- return measurement: adjusted open to adjusted open;
- transaction cost: 10 basis points per turnover unit;
- common three-asset sample: 2024-01-30 through 2026-07-30;
- observations: 627;
- no pre-inception backfill for QQQI;
- all strategies remain `research_only=true` and `trade_ready=false`.

The short QQQI history is the principal evidence limitation.

## Experiment lineage

| Version or study | PR | Primary change | Decision |
|---|---:|---|---|
| Price-only v1 | #261 | Initial MA200-oriented rotation | Reject as primary architecture; recovery clock was too slow |
| Price-repair v2 / VIX v2 | #261 | Multi-stage repair and 50% TQQQ; VIX risk budget | Retain architecture; price repair is the return engine |
| VIX v3 aggressive | #262 | Increase partial leverage from 50% to 75% TQQQ | Retain; do not search leverage weight further |
| Breadth / VXN v4 | #265 | Relative breadth, VXN replacement and dual confirmation | Reject relative breadth hard gate; retain VXN information |
| VXN leverage veto v4.1 | #266 | VXN only vetoes the 75% TQQQ layer | Frozen prospective baseline |
| Long-history attack layer | #272 | Replay frozen VIX/VXN leverage logic from 2010 | Directionally positive but not stable enough for promotion |
| Churn diagnostics | #274 | Diagnose VXN exits and rapid re-entry | Identified short exits; no rule change by itself |
| Two-day VXN persistence | #276 | Require two pressure days before exiting leverage | Reject; turnover fell but all risk-adjusted metrics worsened |
| Absolute breadth soft tier | #278 | Use QQQE absolute trend to scale leverage | Reject; lower exposure did not improve risk budgeting |
| QQQ downside-volatility veto | #279 | Veto leverage on realized downside stress | Reject; duplicated VXN and blocked successful entries |
| HYG/SHY credit proxy | #280 | Credit-risk appetite veto | Positive full sample but concentrated in 2015; do not add |
| Prospective v4.1 monitor | #281 | Weekly frozen monitoring from 2026-08-01 | Active; no automatic promotion |
| **Confidence bridge v4.2** | **#297** | **State 1 becomes 50% QQQI / 50% QQQ; state trace unchanged** | **Retain as post-result monitoring challenger; do not replace v4.1 yet** |

## Current complete result summary

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Total return | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 22.01% | 21.30% | 1.041 | 1.489 | -24.17% | 0.911 | 64.06% | — |
| VIX v3, 75% TQQQ | 29.62% | 26.63% | 1.108 | — | -24.43% | 1.212 | 90.68% | 65 |
| Frozen v4.1 VXN leverage veto | 32.44% | 25.82% | 1.218 | 1.764 | -24.43% | 1.328 | 101.17% | 71 |
| **v4.2 50/50 bridge challenger** | **33.06%** | **25.62%** | **1.244** | **1.801** | **-24.21%** | **1.365** | **103.53%** | **55** |

## Architecture findings

### Price repair and VIX

1. QQQ drawdown provides shock memory.
2. Short- and medium-horizon price repair identifies recovery opportunity.
3. VIX regulates broad-market defense and risk budget.
4. MA200 is a long-term defensive boundary, not the primary recovery clock.

### TQQQ leverage layer

The state-1-to-state-2 transition is the strongest measured signal component. In the complete v4.1 event study, twelve add-leverage events produced about +5.76 percentage points mean twenty-session benefit and approximately 91.7% positive relative outcomes.

VXN is useful only in a narrow role aligned with Nasdaq leverage exposure. It should not replace VIX across the full state machine.

### Initial QQQ risk-on state

The QQQI-to-QQ transition is the weakest measured component: ten events produced only about +0.74 percentage points mean twenty-session relative benefit and approximately 50% positive outcomes.

This does not prove that the entry timing is wrong. It shows that state 1 carries lower confidence than state 2 and may not justify an immediate full QQQ allocation.

### v4.2 confidence bridge

The bridge changes no signal date:

- state 0: 100% QQQI;
- state 1: 50% QQQI + 50% QQQ;
- state 2: 25% QQQ + 75% TQQQ.

Relative to v4.1 it produced:

- total return: +2.36 percentage points;
- CAGR: +0.62 percentage points;
- volatility: -0.20 percentage points;
- Sharpe: +0.026;
- Sortino: +0.037;
- maximum drawdown: +0.22 percentage points of improvement;
- Calmar: +0.037;
- turnover: 71 to 55 units;
- cumulative cost deduction: 7.10% to 5.50%;
- exact same state trace and exact same 129 partial-leverage sessions.

The bridge's gross total return was slightly lower than v4.1. The net improvement came primarily from lower 0-to-1 and 1-to-0 transition friction, plus slightly better realized state-1 downside behavior. Both early and late chronological segments improved.

Decision: retain as a separate post-result monitoring challenger. Do not replace the v4.1 frozen baseline before prospective evidence exists and do not test alternative bridge weights on this sample.

## Long-history structural validation

QQQI is excluded rather than reconstructed. States 0 and 1 map to QQQ and state 2 maps to 25% QQQ / 75% TQQQ.

| Attack-layer strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| QQQ buy and hold | 18.95% | 20.46% | 0.951 | 1.332 | -36.69% | 0.516 |
| Static 25% QQQ / 75% TQQQ | 37.06% | 50.79% | 0.877 | 1.232 | -74.04% | 0.501 |
| Frozen VIX v3 attack layer | 25.81% | 26.12% | 1.011 | 1.428 | -38.58% | 0.669 |
| Frozen v4.1 VXN attack layer | 26.31% | 25.78% | 1.036 | 1.472 | -38.58% | 0.682 |

The VXN benefit is directionally positive but small and concentrated in a few avoided tail losses. It cannot independently validate the full QQQI strategy.

## Rejected optimization hypotheses

- Relative QQQE/QQQ breadth hard gate: removed successful mega-cap-led recoveries.
- Two-day VXN exit persistence: reduced turnover but worsened CAGR, Sharpe, Sortino and Calmar.
- Absolute QQQE breadth soft scaling: reduced exposure without improving risk-adjusted return.
- QQQ realized downside-volatility veto: overlapped VXN and blocked profitable leverage entries.
- HYG/SHY MA50 veto: positive full-sample result was dominated by 2015 and inactive after April 2023.

No rejected rule is active in v4.1 or the bridge challenger.

## Evidence references

| Study | Workflow run | Artifact ID | Evidence digest |
|---|---:|---:|---|
| VIX v3 aggressive | `30689825451` | `8815264414` | `sha256:d6397090d7c8a01bf7c383df849f72ff25c2ad6247b0644522f0f25d022427fb` |
| Breadth / VXN v4 | `30690518926` | `8815500542` | `sha256:74cef0df0e77f5391721946c567997843a35b0920e66573bb03e267e71ac42ac` |
| VXN leverage veto v4.1 | `30690786777` | `8815588121` | `sha256:6184c8e2f4186d4fc90848cb4ceb974c7334d9fce56b9e17eda1ef1a07ce4cd4` |
| Long-history attack layer | `30691947502` | `8815971914` | `sha256:64cb61754392e2c195ebceb5eba46d69cf776ef16abf0b8800f91c5926da973f` |
| Initial prospective monitor | `30694181701` | `8816681833` | `sha256:4e6b27f6910bc630c976d633f8927566789d50f3f417596c0256b6803dcc08a7` |
| **v4.2 bridge challenger** | **`30706201043`** | **`8820398584`** | **`sha256:3b4962b11796ee72ec4f74cca12ddf0d40800cf5417af4e42dabfb3a3d81abbf`** |

## Monitoring candidates

### Frozen baseline

Candidate ID: `qqqi_qqq_tqqq_vxn_leverage_v4_1`

Monitoring start: 2026-08-01.

### Allocation challenger

Candidate ID: `qqqi_qqq_tqqq_vxn_bridge_v4_2`

Status:

- `research_only=true`;
- `trade_ready=false`;
- `post_result_hypothesis=true`;
- same v4.1 signals;
- separate prospective comparison required.

## Next admissible work

Do not continue retrospective threshold, factor or allocation searches on the same sample.

The next valid evidence is prospective:

1. monitor v4.1 and bridge v4.2 side by side from 2026-08-01;
2. preserve both contracts and hashes;
3. record each state-1 interval, transition cost and realized return difference;
4. record each VXN leverage veto and subsequent 5/10/20/40-session outcome;
5. review only after a meaningful number of new state transitions or a predeclared calendar interval;
6. do not promote either candidate automatically.

## Promotion criteria

No strategy should be marked trade ready until:

- prospective out-of-sample evidence exists after 2026-08-01;
- performance is not dominated by one or two episodes;
- turnover and slippage sensitivity remain acceptable;
- the active architecture remains explainable and simple;
- the final contract, evidence hashes and decision are recorded in the journal and this ledger.
