# v4.2 SGOV recovery-release experiment result

**Evidence date:** 2026-08-02  
**Economic sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Current baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Official cost:** 10 basis points per turnover unit  
**Status:** research-only; not trade-ready

## Executive decision

1. Keep v4.2 unchanged as the current research baseline and production alert source.
2. Reject immediate SGOV-to-QQQI release as a promoted challenger.
3. Retain the capped 25% SGOV-to-TQQQ precursor as a promising but deferred shadow hypothesis.
4. Reject the combined staged QQQI-then-TQQQ release as a promoted challenger.
5. Do not change Telegram alerts or create a second actionable signal stream.
6. Do not search additional precursor weights, thresholds or persistence lengths on the current sample.

The central result is that limited early TQQQ exposure improved the static blended profile in both chronological segments and across all three observed precursor episodes. However, the sample contains only three precursor episodes and one major drawdown remains unresolved, so the pre-registered gate does not authorize prospective challenger status.

## 1. Frozen variants

### Current v4.2

- state 0: 100% QQQI;
- state 1: 50% QQQI / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

### Static blended profile

- state 0: 50% QQQI / 50% SGOV;
- state 1: 25% QQQI / 25% SGOV / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

### QQQI release

- state 0 remains blended;
- executed state 1 becomes 50% QQQI / 50% QQQ;
- TQQQ timing remains identical to v4.2.

### TQQQ precursor release

- ordinary state 1 remains blended;
- when shock memory, medium repair and VIX normalization are true and VXN is not stressed, 25% SGOV becomes 25% TQQQ at the next open;
- formal state 2 remains 75% TQQQ.

### Staged release

- state 1 first removes SGOV in favor of QQQI;
- the same frozen precursor then moves 25% QQQI to TQQQ;
- formal state 2 remains unchanged.

## 2. Headline results

| Strategy | CAGR | Volatility | Sharpe | Sortino | Maximum drawdown | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| Current v4.2 | **33.06%** | 25.62% | 1.244 | 1.801 | -24.22% | 1.365 | 55 |
| Static blended | 29.54% | **19.75%** | 1.410 | 2.042 | -17.91% | 1.649 | 55 |
| QQQI release | 30.19% | 20.23% | 1.407 | 2.031 | -17.31% | 1.744 | 55 |
| TQQQ precursor release | 31.20% | 19.79% | **1.472** | **2.137** | -17.35% | 1.798 | 55 |
| Staged release | 31.45% | 20.26% | 1.452 | 2.101 | **-16.84%** | **1.868** | 55 |

Relative to the static blended profile:

- QQQI release improves CAGR by about 0.65 percentage points;
- TQQQ precursor release improves CAGR by about 1.66 percentage points;
- staged release improves CAGR by about 1.92 percentage points.

Relative to v4.2, all three release structures still retain materially shallower drawdowns, but none matches v4.2's CAGR.

## 3. QQQI release — useful mechanism, failed candidate

Immediate SGOV-to-QQQI release in state 1 produced:

- CAGR: 30.19%;
- maximum drawdown: -17.31%;
- median resolved major-episode recovery lag: 0 sessions;
- median major-trough protection: 4.38 percentage points.

This confirms that keeping SGOV in state 1 contributes materially to slow recovery. However, the candidate fails the full gate:

- CAGR sacrifice versus v4.2 is 2.87 percentage points, above the 2-point limit;
- late-segment CAGR is about 0.84 percentage points below the static blended profile;
- one major episode remains unresolved;
- the current 2026-06-02 drawdown has negative same-trough protection of about -0.97 percentage points.

The conclusion is not that QQQI release is ineffective. It is that unconditional release at every state-1 entry is too broad and sacrifices some late-sample protection.

## 4. TQQQ precursor release — best controlled candidate

The precursor allocation was active for only six sessions across three contiguous events:

| Event | Dates | Sessions | Event relative return versus static blend |
|---|---|---:|---:|
| 1 | 2024-08-16 to 2024-08-21 | 4 | +1.82% |
| 2 | 2024-11-07 | 1 | +0.58% |
| 3 | 2026-04-09 | 1 | +0.64% |

Results:

- all three precursor events were positive;
- largest positive event share: 59.87%, just below the 60% ceiling;
- early-segment CAGR improves by 2.02 percentage points versus static blended;
- late-segment CAGR improves by 1.00 percentage point;
- CAGR sacrifice versus v4.2 is 1.86 percentage points, within the 2-point limit;
- all five major v4.2 troughs remain improved;
- median major-trough protection remains 4.38 percentage points;
- maximum drawdown improves to -17.35%.

This is the only variant that passes every economic and chronological check. It fails the formal gate only because one major episode remains unresolved at the sample end.

Nevertheless, the evidence base is very small: three precursor events, with the largest event contributing almost 60% of positive benefit. The result is therefore recorded as a deferred shadow hypothesis rather than an authorized challenger.

## 5. Staged QQQI then TQQQ release — stronger headline, weaker stability

The staged structure produces the highest release-variant CAGR and best maximum drawdown:

- CAGR: 31.45%;
- maximum drawdown: -16.84%;
- Calmar: 1.868.

But it does not pass:

- late-segment CAGR is about 0.12 percentage points below the static blended profile;
- only four of the five major troughs remain improved;
- the current unresolved episode has about -0.97 percentage points of protection;
- one major episode remains unresolved.

The combined rule inherits the QQQI-release weakness while adding the TQQQ precursor benefit. The extra complexity is not justified by the chronological evidence.

## 6. Recovery-lag interpretation

The prior static blended profile had resolved major-event recovery lags of 0, 114, -4 and 132 sessions, plus one unresolved event. Its median resolved lag was 57 sessions.

The new variants show:

| Variant | Median resolved lag | Notable long lag | Unresolved major events |
|---|---:|---:|---:|
| Static blended | 57 sessions | 132 sessions | 1 |
| QQQI release | 0 sessions | 131 sessions | 1 |
| TQQQ precursor release | -0.5 sessions | 128 sessions | 1 |
| Staged release | -0.5 sessions | 126 sessions | 1 |

The median improves sharply because the 2024-07 recovery becomes contemporaneous or slightly earlier. However, the very long 2024-02 recovery remains largely unchanged, and the ongoing 2026 episode prevents a complete judgment.

Therefore, the proper conclusion is:

> Earlier release can improve typical recovery speed, but it has not yet demonstrated that it solves the long-tail recovery problem.

## 7. Tail-risk context

The TQQQ precursor release keeps the static profile's main risk advantages:

- expected shortfall 95%: approximately -3.05%, versus -3.93% for v4.2;
- worst 5-day return: approximately -11.37%, versus -12.31% for v4.2;
- worst 20-day return: approximately -12.09%, versus -14.58% for v4.2;
- ulcer index: approximately 0.0656, versus 0.0698 for v4.2.

Its maximum underwater run remains about 194 sessions. The limited precursor improves return and drawdown depth but does not eliminate the broader slow-recovery characteristic of the SGOV profile.

## 8. Final research status

### Retained

- v4.2 remains the only current research baseline and alert source;
- the static blended profile remains the descriptive drawdown-first allocation;
- `tqqq_release_on_precursor` is retained as a deferred shadow hypothesis.

### Rejected

- unconditional QQQI release as a promoted challenger;
- staged QQQI-then-TQQQ release as a promoted challenger;
- any additional retrospective search over release weights or thresholds.

### Next admissible evidence

The precursor hypothesis should be reconsidered only after:

- the currently unresolved major drawdown is resolved or reaches a formally censored review date; and
- at least three additional prospective precursor events are observed, bringing the total to at least six.

Until then, no Telegram action card or target allocation should be generated from the precursor rule. It may be logged as a non-actionable shadow field inside the existing v4.2 prospective evidence stream.

## 9. Evidence

- workflow: `QQQI v4.2 SGOV Recovery Release`;
- workflow run: `30735777927`;
- artifact ID: `8829513797`;
- artifact digest: `sha256:dc631ede180e2dff39fc4094fdca049c65551ef13cb6b3cd66c115a35e7e733f`;
- notebook: `notebooks/22_qqqi_qqq_tqqq_v4_2_sgov_recovery_release.ipynb`.

The evidence bundle contains daily weights and returns, trades, five-major-trough tables, chronological metrics, precursor-event tables, candidate gates, tail-risk metrics and the executed notebook.
