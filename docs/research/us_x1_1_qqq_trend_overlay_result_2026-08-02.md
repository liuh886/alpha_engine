# US x1.1 QQQ trend-overlay validation

**Date:** 2026-08-02  
**Issue / PR:** #396 / #400  
**Decision:** `trend_overlay_destroys_too_much_upside`  
**Model consequence:** US x1.1 unchanged; no US x1.2 candidate  
**Operational status:** research only; `trade_ready=false`

## Question

Phase A drawdown attribution found that reducing gross exposure to 50% when the
QQQ trailing-20-session price trend was negative improved the difficult 2025H1
window. Issue #396 tested whether that rule was a broadly useful portfolio
contract or only a regime-specific response.

The experiment compared exactly three fixed contracts:

1. 100% gross at all times;
2. 50% gross when QQQ trailing-20-session trend was negative;
3. 0% gross when the same trend was negative.

No model fitting, score change, lookback search, threshold search or combined
control was allowed.

## Frozen evidence

- provider: `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95`;
- decision windows: 2024H1, 2024H2, 2025H1 and 2025H2;
- 2026H1 excluded;
- exact Experiment 007 source-score and source-selection artifacts;
- Top-15 equal weight before gross-exposure overlay;
- ten-session holding and rebalance;
- 20, 40 and 60 bps cost stress.

The source artifact SHA remained the authoritative byte identity. Daily Top-15
selections were also reconstructed semantically. Economic score and selection
identities were recorded separately after intersecting scores with available
raw forward returns.

## Aggregate result

### 20 bps

| Contract | Compounded strategy return | Relative excess vs QQQ | Retained baseline excess | Worst drawdown | Positive windows | Average gross |
|---|---:|---:|---:|---:|---:|---:|
| Baseline 100% | 231.11% | 113.35% | 100.0% | -33.88% | 4/4 | 100.0% |
| QQQ-negative 50% | 190.08% | 86.91% | 76.68% | -27.66% | 4/4 | 87.5% |
| QQQ-negative cash | 149.75% | 60.93% | 53.75% | -21.15% | 3/4 | 75.0% |

The 50% overlay improved the worst drawdown by 6.21 percentage points, and the
cash overlay improved it by 12.73 percentage points. Both failed the requirement
to retain at least 90% of baseline compounded relative excess.

### Cost stress

| Contract | Relative excess, 20 bps | 40 bps | 60 bps |
|---|---:|---:|---:|
| Baseline 100% | 113.35% | 102.96% | 93.07% |
| QQQ-negative 50% | 86.91% | 78.74% | 70.91% |
| QQQ-negative cash | 60.93% | 54.71% | 48.72% |

Both overlays remained positive at 60 bps. Cost survival was therefore not the
reason for rejection; the binding problems were excess retention and lack of
cross-window drawdown benefit.

## Window evidence at 20 bps

| Window | Contract | Excess vs QQQ | Maximum drawdown | Drawdown change vs baseline | Reduced-risk rebalances |
|---|---|---:|---:|---:|---:|
| 2024H1 | Baseline | 11.75% | -6.87% | — | 0/12 |
| 2024H1 | 50% | 3.65% | -6.87% | 0.00 pp | 2/12 |
| 2024H1 | Cash | -4.45% | -6.87% | 0.00 pp | 2/12 |
| 2024H2 | Baseline | 32.37% | -13.97% | — | 0/12 |
| 2024H2 | 50% | 28.13% | -14.05% | -0.08 pp | 2/12 |
| 2024H2 | Cash | 23.93% | -16.72% | -2.75 pp | 2/12 |
| 2025H1 | Baseline | 5.54% | -33.88% | — | 0/12 |
| 2025H1 | 50% | 7.62% | -27.66% | +6.21 pp | 6/12 |
| 2025H1 | Cash | 9.06% | -21.15% | +12.73 pp | 6/12 |
| 2025H2 | Baseline | 47.19% | -19.38% | — | 0/12 |
| 2025H2 | 50% | 38.49% | -19.38% | 0.00 pp | 2/12 |
| 2025H2 | Cash | 29.32% | -19.46% | -0.08 pp | 2/12 |

Only 2025H1 achieved the pre-registered one-percentage-point material drawdown
benefit. The required benefit in at least two of four windows therefore failed
for both overlays.

## Mechanism

The rule was useful when a persistent market deterioration followed the initial
shock. In 2025H1, negative-trend exposure occurred in six of twelve rebalances:

- the 50% rule reduced maximum drawdown from -33.88% to -27.66%;
- the cash rule reduced it to -21.15%;
- both overlay paths recovered by 2025-06-12, while the baseline had not
  recovered within the window.

Outside that episode, negative-trend signals frequently coincided with rebounds
or recoverable weakness. The 50% overlay gave up excess in all three other
windows, while cash created negative excess in 2024H1 and delayed the 2024H2
recovery by 28 calendar days.

Across the four windows, the arithmetic baseline-minus-overlay return forgone
on negative-trend rebound periods was approximately 25.10 percentage points for
the 50% rule and 50.20 percentage points for cash. These figures are period
contribution diagnostics, not compounded performance measures.

## Candidate gates

### QQQ-negative 50%

- worst drawdown improvement >= 4 pp: **pass**;
- retain >= 90% baseline relative excess: **fail** at 76.68%;
- positive relative excess at 60 bps: **pass**;
- no newly negative baseline-positive window: **pass**;
- material drawdown benefit in at least two windows: **fail**, 1/4.

### QQQ-negative cash

- worst drawdown improvement >= 4 pp: **pass**;
- retain >= 90% baseline relative excess: **fail** at 53.75%;
- positive relative excess at 60 bps: **pass**;
- no newly negative baseline-positive window: recorded 2024H1 failure; the
  separate 8 pp drawdown override was met;
- material drawdown benefit in at least two windows: **fail**, 1/4.

## Conclusion

The QQQ trailing-20-session trend is a valid explanation and tactical control
for the continuation phase of the 2025H1 drawdown, but it is not a sufficiently
broad portfolio regime contract. A fixed 50% or cash response reacts too late
to the initial shock and sacrifices too much recovery and upside in otherwise
profitable windows.

The result rejects both pre-registered overlays as portfolio-contract
candidates. US x1.1 remains unchanged. Future work should not tune the same
lookback or threshold on these four consumed windows; any new regime-control
hypothesis requires a distinct causal signal and independent evidence.
