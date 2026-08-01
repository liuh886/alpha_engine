# QQQI / QQQ / partial-TQQQ VIX v2: Live-Data Result

## Status

- Experiment: `qqqi_qqq_tqqq_vix_v2`
- Evidence cutoff requested: 2026-08-01
- Latest completed market session: 2026-07-31
- Economic return sample: 2024-01-30 through 2026-07-30
- Observations: 627 adjusted open-to-open returns
- Boundary: `research_only=true`, `trade_ready=false`

QQQI began trading in January 2024, so this is still a short common-history test.
The result is useful for mechanism selection but is not independent evidence
across a complete market cycle.

## Executive conclusion

Introducing VIX improved the strategy's **risk budget**, not its raw return
engine.

The frozen VIX v2 exceeded buy-and-hold QQQ on CAGR, maximum drawdown, Sharpe
and Calmar in the observed common sample. However, a matched price-repair
ablation produced higher CAGR and Sharpe while suffering a materially deeper
maximum drawdown. The incremental VIX effect was therefore defensive:

- VIX v2 versus matched price-repair v2:
  - CAGR: **-2.66 percentage points**
  - maximum-drawdown improvement: **+4.25 percentage points**
  - Sharpe: **-0.024**
  - Calmar: **+0.081**
- VIX v2 versus QQQ:
  - CAGR: **+4.66 percentage points**
  - maximum-drawdown improvement: **+0.94 percentage points**
  - Sharpe: **+0.055**
  - Calmar: **+0.238**

The correct interpretation is not “VIX predicts the rebound.” It is:

> Price repair identifies the recovery opportunity; VIX determines how much
> risk the portfolio is allowed to take while that recovery develops.

## Strategy comparison

| Strategy | CAGR | Volatility | Sharpe | Max drawdown | Calmar | Switches |
|---|---:|---:|---:|---:|---:|---:|
| Buy & Hold QQQ | 22.01% | 21.30% | 1.041 | -24.17% | 0.911 | 0 |
| Price-only v1 | 20.39% | 20.80% | 0.997 | -23.69% | 0.861 | 5 |
| Price-repair v2, no VIX | 29.33% | 26.03% | 1.119 | -27.48% | 1.068 | 24 |
| VIX v2 | 26.67% | 24.29% | 1.095 | -23.23% | 1.148 | 36 |

The revised price-repair logic solved the unreachable-TQQQ problem in v1. Both
matched v2 challengers reached all three intended states.

## What VIX changed

### Exposure

| Strategy | QQQI | QQQ | Partial-leverage state | Average TQQQ weight |
|---|---:|---:|---:|---:|
| Price-repair v2 | 29.03% | 40.03% | 30.94% | 15.47% |
| VIX v2 | 58.69% | 18.82% | 22.49% | 11.24% |

VIX reduced both the frequency and average size of leveraged exposure. It also
kept the portfolio in QQQI much longer. This explains the lower drawdown, but it
also explains part of the lost CAGR.

### Turnover

- Price-repair v2: 24 switches, 34 turnover units, 3.4% summed daily cost deductions.
- VIX v2: 36 switches, 57 turnover units, 5.7% summed daily cost deductions.

The VIX layer improved drawdown despite higher turnover, but the extra switching
is a clear weakness. Future work should add hysteresis or minimum-holding rules
only through a separately versioned contract; thresholds must not be adjusted
inside this completed result.

## VIX regime evidence

VIX regimes were determined at close `t`; returns begin at the next executable
open.

| VIX regime | Sessions | QQQI return | QQQ return | QQQI vol | QQQ vol | QQQI MDD | QQQ MDD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Calm | 242 | -0.20% | 2.40% | 11.53% | 15.15% | -10.94% | -12.94% |
| Normal | 228 | 15.20% | 20.06% | 18.70% | 18.06% | -10.28% | -12.64% |
| Stress | 156 | 33.92% | 35.56% | 29.06% | 31.32% | -15.46% | -17.52% |

QQQI consistently reduced volatility and drawdown, including during VIX stress,
but QQQ generally retained higher cumulative return. This supports using QQQI
as a defensive allocation rather than claiming that it dominates QQQ during
fear regimes.

## VIX event study

Nine VIX stress clusters were identified, although the most recent cluster lacks
complete forward horizons.

VIX easing and normalization did not consistently make QQQ outperform QQQI over
10- or 20-session horizons. For example, among eight complete easing events,
QQQ led in five at 5 sessions, four at 10 sessions and only two at 20 sessions.
The event study therefore does not establish VIX retreat as a standalone rebound
signal.

This finding is important: the VIX layer should not replace QQQ price repair.
Its observed value comes from controlling state transitions and leverage, not
from a stable unconditional return spread after VIX falls.

## Chronological split

The rules were frozen and applied to early and late common-history segments.

| Strategy | Segment | CAGR | Sharpe | Max drawdown | Calmar |
|---|---|---:|---:|---:|---:|
| Price-repair v2 | Early | 26.94% | 1.005 | -27.48% | 0.980 |
| Price-repair v2 | Late | 33.00% | 1.325 | -15.50% | 2.130 |
| VIX v2 | Early | 23.38% | 0.946 | -23.23% | 1.006 |
| VIX v2 | Late | 31.78% | 1.366 | -16.61% | 1.913 |

Both challengers remained positive in both segments. The VIX layer had the
smaller early-sample drawdown and stronger early Calmar; the no-VIX challenger
had higher CAGR. The late sample favored VIX on Sharpe but not on drawdown or
Calmar. This is encouraging but still based on one short chronological split.

## Recommended strategy architecture

The evidence supports retaining four distinct responsibilities:

1. **Shock memory** — QQQ drawdown identifies that a recovery opportunity may
   exist.
2. **Price repair** — 5-day breakout / rising MA20 moves QQQI to QQQ; MA50 plus
   secondary confirmation permits partial leverage.
3. **VIX risk budget** — easing permits risk restoration; normalization permits
   partial TQQQ; renewed stress removes leverage or returns the portfolio to
   defense when price also fails.
4. **MA200 boundary** — remains a long-term defensive boundary, not the recovery
   clock.

The current 50% QQQ / 50% TQQQ leveraged state should remain a research cap.
The evidence does not justify 100% TQQQ.

## Decision

- **VIX inclusion:** supported as a defensive overlay.
- **VIX as a standalone recovery predictor:** not supported.
- **Revised price repair:** materially more promising than v1.
- **VIX v2 trade readiness:** not established.
- **Next priority:** reduce VIX-induced churn and test the frozen mechanism on
  additional genuinely out-of-sample data rather than retuning this sample.
