# v4.2 SGOV recovery precursor — 50% TQQQ result

**Evidence date:** 2026-08-02  
**Economic sample:** 2024-01-30 through 2026-07-30  
**Observations:** 627 adjusted open-to-open returns  
**Official cost:** 10 basis points per turnover unit  
**Status:** research-only; not trade-ready

## Executive decision

1. The fixed 50% TQQQ precursor is economically superior to the previously retained 25% precursor on the current historical sample.
2. It becomes the **preferred deferred shadow hypothesis** for prospective evidence collection.
3. It does not become an actionable signal or alter Telegram target weights.
4. The 25% precursor remains an immutable comparator.
5. No further precursor weight search is authorized on the current sample.

The 50% variant passes every completed economic, chronological, concentration and tail-risk check. It fails the full shadow-monitor gate only because there are three historical precursor events rather than six and one major drawdown remains unresolved.

## 1. Fixed comparison

### Ordinary blended state 1

- 25% QQQI;
- 25% SGOV;
- 50% QQQ;
- 0% TQQQ.

### Frozen 25% precursor

- 25% QQQI;
- 0% SGOV;
- 50% QQQ;
- 25% TQQQ.

### New 50% precursor

- 0% QQQI;
- 0% SGOV;
- 50% QQQ;
- 50% TQQQ.

The 25% and 50% variants use exactly the same precursor dates. The extra 25% TQQQ is funded by removing the remaining 25% QQQI. Formal state 2 remains 25% QQQ / 75% TQQQ.

## 2. Headline results

| Strategy | CAGR | Volatility | Sharpe | Sortino | Maximum drawdown | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| Current v4.2 | **33.06%** | 25.62% | 1.244 | 1.801 | -24.22% | 1.365 | 55 |
| Static blended SGOV | 29.54% | **19.75%** | 1.410 | 2.042 | -17.91% | 1.649 | 55 |
| 25% TQQQ precursor | 31.20% | 19.79% | 1.472 | 2.137 | -17.35% | 1.798 | 55 |
| **50% TQQQ precursor** | **32.47%** | 19.85% | **1.517** | **2.209** | **-16.89%** | **1.923** | 55 |

Relative to the 25% precursor, the 50% variant produces:

- CAGR improvement: **+1.27 percentage points**;
- Sharpe improvement: **+0.0448**;
- Sortino improvement: **+0.0724**;
- maximum-drawdown improvement: **+0.47 percentage points**;
- Calmar improvement: **+0.125**;
- no increase in total turnover or modeled transaction cost.

Relative to v4.2, the CAGR gap narrows to approximately **0.59 percentage points**, while maximum drawdown remains about **7.34 percentage points shallower**.

## 3. Chronological stability

| Segment | Static blended CAGR | 25% precursor CAGR | 50% precursor CAGR | 50% minus 25% |
|---|---:|---:|---:|---:|
| Early | 20.45% | 22.47% | **24.04%** | **+1.57 pp** |
| Late | 44.44% | 45.44% | **46.17%** | **+0.72 pp** |

The extra 25% TQQQ improves both chronological segments. The result is therefore not confined to the early sample.

## 4. Event-level marginal contribution

The precursor occurs on the same six sessions and three events as the 25% variant:

| Event | Dates | Sessions | 50% minus 25% event return | 50% minus static blend |
|---|---|---:|---:|---:|
| 1 | 2024-08-16 to 2024-08-21 | 4 | **+1.34%** | +3.19% |
| 2 | 2024-11-07 | 1 | **+0.46%** | +1.04% |
| 3 | 2026-04-09 | 1 | **+0.45%** | +1.09% |

- marginal event positive rate versus 25%: **100%**;
- largest-event share of positive marginal benefit: **59.50%**;
- pre-registered concentration ceiling: 65%.

The 50% result is still based on only three events, but the extra return is not supplied by a single event alone.

## 5. Tail risk

| Metric | 25% precursor | 50% precursor | Direction |
|---|---:|---:|---|
| Expected shortfall 95% | -3.053% | **-3.051%** | slightly better |
| Worst 5-day return | -11.371% | -11.371% | unchanged |
| Worst 20-day return | -12.091% | **-12.046%** | slightly better |
| Maximum drawdown | -17.353% | **-16.886%** | better |
| Ulcer index | 0.0656 | **0.0640** | better |
| Maximum underwater run | 194 sessions | 194 sessions | unchanged |

No pre-registered tail-risk limit is breached. This occurs because the precursor was active only during six historically positive recovery sessions. It should not be interpreted as proof that 50% TQQQ is intrinsically safer; it means the observed precursor timing offset the additional leverage in this limited sample.

## 6. Major drawdown protection and recovery

The 50% precursor retains positive protection at all five major v4.2 troughs:

- major-trough improvement rate: **100%**;
- median same-trough protection: **4.64 percentage points**;
- median resolved recovery lag: **-1 session**;
- one major episode remains unresolved;
- the longest historical recovery lag remains **125 sessions**.

The current unresolved 2026 episode still has positive same-trough protection of approximately **0.71 percentage points**. This is better than the unconditional QQQI-release variants, which lost protection in the same episode.

The 50% precursor improves typical recovery but does not eliminate the long-tail recovery problem.

## 7. Pre-registered gate

The 50% variant passes:

- full-sample CAGR improvement versus 25%;
- early- and late-sample CAGR improvement;
- Sharpe requirement;
- event positive-rate and concentration requirements;
- maximum drawdown, expected-shortfall and worst-window limits;
- major-trough improvement and median protection requirements.

It fails:

- minimum event count: **3 observed versus 6 required**;
- unresolved major episodes: **1 observed versus 0 required**.

**Decision:** `preferred_deferred_shadow_hypothesis`.

No actionable alert, target allocation or direct model promotion is authorized.

## 8. Research interpretation

The experiment supports a more precise recovery architecture:

> During the narrow interval in which medium repair and volatility normalization are already observable but formal state-2 confirmation is incomplete, 50% TQQQ captured more rebound than 25% TQQQ without worsening the measured historical tail profile.

However, three events are insufficient to conclude that the 50% exposure is structurally robust. The result could still reverse in a failed recovery event.

## 9. Next evidence

Issue #348 should record, without actionable alerts:

- the frozen precursor boolean;
- the hypothetical 25% and 50% TQQQ allocations;
- the next-open prices;
- 5-, 10-, 20- and 40-session outcomes;
- marginal 50%-versus-25% performance;
- any failed recovery or renewed volatility stress.

The 50% hypothesis may be reconsidered for a dedicated shadow monitor only after:

- at least three additional prospective precursor events, bringing the total to six; and
- the current unresolved major episode is resolved or formally censored.

No 35%, 40%, 60% or other precursor weight should be tested on the current sample.

## 10. Evidence

- workflow: `QQQI v4.2 SGOV Precursor 50`;
- workflow run: `30737397224`;
- artifact ID: `8830077965`;
- artifact digest: `sha256:8885741183b30177e70f380e0a6286c0b33d0aa375c279356592be5c0fca26c6`;
- notebook: `notebooks/23_qqqi_qqq_tqqq_v4_2_sgov_precursor_50.ipynb`.
