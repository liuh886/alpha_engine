# QQQ/TQQQ v4.1 churn diagnostic result

Date: 2026-08-01

Experiment: `qqq_tqqq_vxn_v4_1_churn_diagnostics`

Status: `research_only=true`, `trade_ready=false`, `diagnostic_only=true`, `strategy_rule_changed=false`

## Decision

The diagnostics identify a clear and recurring short-exit churn problem. A separate single-rule persistence experiment is admissible.

Do not remove VXN and do not introduce a broad cooldown. The evidence indicates that longer VXN exits delivered protection, while most rapid VXN-only exits were quickly reversed and economically harmful.

The only admissible next hypothesis is narrow:

- preserve the immediate VXN veto on new leveraged entries;
- while already leveraged, require VXN stress to persist for two consecutive closes before VXN alone forces an exit;
- retain immediate exits for VIX stress and the existing MA20 price failure;
- change no VIX/VXN threshold, price rule or TQQQ weight.

This is one predeclared rule, not a search over persistence lengths.

## Sample and frozen strategy

- sample: 2010-10-18 through 2026-07-31;
- baseline: frozen VIX v3 attack layer;
- overlay: frozen v4.1 VXN leverage veto;
- QQQI excluded;
- source states 0 and 1 map to QQQ;
- source state 2 maps to 25% QQQ / 75% TQQQ;
- close signal, next-open execution;
- 10 bps cost per turnover unit.

No strategy rule changed in this diagnostic.

## Dwell-time evidence

| Metric | VIX v3 | VXN v4.1 |
|---|---:|---:|
| Leveraged episodes | 42 | 46 |
| Median leveraged dwell | 16 sessions | 14 sessions |
| Episodes no longer than 5 sessions | 13 | 16 |
| Episodes no longer than 10 sessions | 17 | 20 |
| Episodes no longer than 20 sessions | 25 | 29 |

The VXN overlay created four additional leveraged episodes and shortened median dwell time.

Short leveraged episodes were generally poor in both strategies, but VXN increased their frequency. Among VXN episodes lasting no more than five sessions, 81.25% lost money.

## Re-entry evidence

| Metric | VIX v3 | VXN v4.1 |
|---|---:|---:|
| Completed exit-to-reentry cycles | 41 | 45 |
| Re-entry within 5 sessions | 15 | 19 |
| Same-calendar-month re-entry | 15 | 19 |
| Median re-entry gap | 14 sessions | 10 sessions |

The four incremental cycles created by VXN were all rapid same-month reversals.

## VXN-only exits

Eight exits were caused uniquely by VXN while the VIX-only baseline remained leveraged.

| Exit date | Re-entry gap | Relative result while positions differed | Assessment |
|---|---:|---:|---|
| 2015-10-15 | 1 session | -2.37 pp | Harmful rapid exit |
| 2020-07-14 | 4 sessions | -2.58 pp | Harmful rapid exit |
| 2020-09-03 | 25 sessions | +6.30 pp | Helpful protective exit |
| 2020-10-27 | 9 sessions | +1.63 pp | Helpful protective exit |
| 2024-08-27 | 1 session | -0.92 pp | Harmful rapid exit |
| 2024-09-17 | 3 sessions | +0.35 pp | Modestly helpful rapid exit |
| 2026-05-12 | 3 sessions | -0.38 pp | Harmful rapid exit |
| 2026-05-18 | 1 session | +2.28 pp | Helpful rapid exit |

Six of eight exits re-entered within five sessions. Only two of those six rapid exits added value.

Aggregate attribution:

- rapid exits, re-entry within five sessions: **-3.63 percentage points**;
- longer exits: **+7.93 percentage points**.

This separation is the key finding. VXN's useful contribution came from persistent stress episodes, while isolated stress observations often caused unnecessary position churn.

## Cost evidence

Relative to VIX v3, v4.1 generated:

- switches: 84 to 92;
- turnover units: 127 to 139;
- incremental turnover: 12 units;
- incremental explicit cost at 10 bps: 1.20 percentage points cumulatively.

The VXN variant executed 46 leveraged entries versus 42 for the baseline and 33 leveraged exits versus 29. The extra entries and exits are consistent with the four additional short cycles.

## Why a broad cooldown is not justified

A fixed post-exit cooldown could delay entry after genuinely protective exits and would also interfere with VIX- or price-driven transitions. The observed problem is narrower: VXN stress sometimes lasts only one close.

The next rule should therefore change only the VXN-only exit path. Entry vetoes remain immediate because the strategy does not yet hold leveraged risk. Existing VIX and price exits also remain immediate because they represent broader or directly observed risk failure.

## Next experiment

Test exactly one challenger:

> While already in the leveraged state, VXN alone may force an exit only after two consecutive VXN-stress closes. VXN continues to veto new leveraged entries immediately. VIX stress and MA20 failure continue to exit immediately.

This rule is selected from the mechanism identified by the diagnostics, not from a parameter grid. No one-day/three-day/five-day comparison is permitted.

## Evidence

- workflow run: `30692364844`;
- artifact ID: `8816103731`;
- evidence digest: `sha256:1ab6355419df866fbf656037a0ce065f00278f4060688415f5f43546763e444b`.
