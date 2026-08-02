# US x1.1 2025H1 drawdown attribution — Phase A

## Decision

**`portfolio_control_path_supported`**

The deterministic US x1.1 2025H1 portfolio path was reproduced exactly and
attributed by rebalance, name, transaction cost, trailing volatility, QQQ beta
and QQQ trend state. Neither the pre-registered name-concentration gate nor the
regime-dominance gate was met. One isolated control did pass its portfolio
improvement gate: reducing gross exposure to 50% when the QQQ 20-session trend
was negative.

This is mechanism evidence, not a model update. US x1.1 remains unchanged,
`research_only=true` and `trade_ready=false`.

## Evidence identity

- Issue / PR: #381 / #395;
- workflow run: `30743901477`;
- artifact: `8832228801`;
- artifact digest:
  `sha256:1090a80220a0c9aa1b4b326faa721be09a0a7bd7a7b333bbac5e1887637b8582`;
- frozen provider:
  `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95`;
- complete model score identity:
  `3e4390f38615118ab3ae0218e0d4df7855a82654b829584db47520685b7b0301`;
- economically aligned score identity:
  `5f696d3decfd3c03d2d651e47a3ba9fc4c1fcec647ba79156d92c2cdcb41aaf1`.

## Score-to-economics alignment

The model produced 9,744 score observations in 2025H1. Canonical economic
evaluation intersects these scores with non-null raw forward 10-session
returns before cross-sectional ranking and selection.

- economic observations: 9,611;
- excluded observations: 133;
- dates with at least one exclusion: 105;
- maximum exclusions on one date: 2.

This explicit alignment was required to reproduce Experiment 007 exactly. The
complete model-score identity remains preserved and is not overwritten by the
economic score ledger.

## Baseline reproduction

The attribution engine reproduced the exact Experiment 007 2025H1 result
within `1e-6` on all governed metrics:

| Metric | US x1.1 2025H1 |
|---|---:|
| Strategy return, 20 bps | +13.2439% |
| QQQ return | +7.7012% |
| Simple excess | +5.5427% |
| Maximum drawdown | -33.8771% |
| Turnover | 7.0333 |
| Transaction costs | 1.4067% |
| Rebalance periods | 12 |
| Positive-excess periods | 8 |

For every rebalance, the sum of name-level gross contribution minus allocated
buy, reduction and exit costs equals the portfolio net return to `1e-12`.

## Drawdown path

- peak: 2025-02-03, NAV 1.1659;
- trough: 2025-04-01, NAV 0.7709;
- peak-to-trough drawdown: -33.8771%;
- recovery within 2025H1: no.

The path contains two different phases:

1. **Initial shock:** the 2025-02-18 period lost 21.07% while the QQQ 20-day
   trend was still positive. A backward-looking trend overlay could not avoid
   this first break.
2. **Continuation:** the 2025-03-04, 2025-03-18 and 2025-04-01 rebalances
   occurred with negative QQQ 20-day trend and extended the drawdown.

This distinction explains why the overlay materially reduces the trough but
does not eliminate the structural 2025H1 loss.

## Name contribution

Largest net negative contributors during the peak-to-trough interval:

| Rank | Name | Net contribution |
|---|---|---:|
| 1 | APP | -4.05% |
| 2 | HIMX | -2.90% |
| 3 | TEM | -2.79% |
| 4 | HIMS | -2.41% |
| 5 | PLTR | -2.14% |
| 6 | HOOD | -2.12% |
| 7 | NBIS | -2.07% |
| 8 | IREN | -1.99% |
| 9 | INTC | -1.71% |
| 10 | BE | -1.65% |

The top three negative names account for only **24.65%** of total negative name
contribution. This is far below the 50% name-concentration gate.

Recurring-name contribution during the drawdown:

| Name | Net contribution |
|---|---:|
| IREN | -1.99% |
| BE | -1.65% |
| AAOI | -1.34% |
| AEHR | -1.09% |
| TYGO | -0.72% |

The recurring set matters, but it does not explain most of the drawdown.

### Leave-one-name-out

The strongest single-name drawdown improvement came from excluding APP:

- drawdown: -32.31%;
- improvement: +1.56 percentage points;
- excess change: +4.62 percentage points.

No single exclusion improved drawdown by the pre-registered four-percentage-
point threshold. The name-dominance gate therefore failed.

## Volatility, beta and trend attribution

Net contribution over the drawdown interval:

### Volatility buckets

| Bucket | Net contribution |
|---|---:|
| Low volatility | -12.26% |
| Mid volatility | -12.64% |
| High volatility | -13.18% |

### QQQ beta buckets

| Bucket | Net contribution |
|---|---:|
| Low beta | -16.15% |
| Mid beta | -13.20% |
| High beta | -8.73% |

Losses were broad across volatility buckets. High-volatility and high-beta
stocks were not the dominant source; the low-beta bucket produced the largest
negative contribution.

### QQQ trend state

| State | Net contribution |
|---|---:|
| Negative 20D trend | -17.01% |
| Non-negative 20D trend | -21.07% |

Negative-trend periods account for **52.72%** of negative contribution, below
the 60% regime-dominance threshold. The initial 2025-02-18 shock occurred before
the trend state turned negative.

## Independent portfolio controls

All controls used the same frozen scores. No controls were combined.

| Strategy | Return | Excess | Max DD | DD change | Excess retained | Gate |
|---|---:|---:|---:|---:|---:|---|
| Baseline Top-15 equal | 13.24% | 5.54% | -33.88% | — | 100% | baseline |
| Top-20 equal | 9.44% | 1.74% | -33.92% | -0.04 pp | 31.4% | fail |
| Top-15 inverse-vol, 10% cap | 14.95% | 7.24% | -33.39% | +0.49 pp | 130.7% | fail DD |
| Top-15 equal, 8% name cap | 13.24% | 5.54% | -33.88% | 0.00 pp | 100% | null |
| QQQ negative-trend 50% gross | 15.32% | 7.62% | -27.66% | **+6.21 pp** | **137.5%** | **pass** |

### Interpretation

- **Top-20 dilution fails.** It does not improve drawdown and destroys most of
  the excess.
- **Inverse volatility is not enough.** It improves return but reduces drawdown
  by only 0.49 percentage point.
- **The 8% name cap is mechanically null.** Equal-weight Top-15 positions are
  approximately 6.67%, already below the cap.
- **The QQQ trend overlay is the only supported path.** It lowers turnover and
  cuts the continuation phase of the drawdown, improving maximum drawdown by
  6.21 percentage points while increasing 2025H1 excess.

The overlay does not prove that the drawdown is wholly regime-dominated; it is
a useful risk-control path because it limits losses after market deterioration
becomes observable.

## Accepted learning

- The 2025H1 drawdown is distributed across many names rather than dominated by
  one or three positions.
- It is not explained primarily by high volatility or high QQQ beta.
- The first large loss occurs before the trend filter turns negative.
- Subsequent negative-trend rebalances materially extend the drawdown.
- A simple delayed regime control can improve the path even though it cannot
  prevent the initial shock.
- Score-to-return alignment is part of the economic evidence contract and must
  remain explicit in future attribution workflows.

## Rejected learning

- Removing APP or any other single name is not a sufficient risk solution.
- Expanding from Top-15 to Top-20 is not diversification in an economically
  useful sense for this signal.
- The existing 8% name cap does not constrain an equal-weight Top-15 portfolio.
- Inverse-volatility weighting alone does not meet the drawdown gate.
- Phase A does not support changing US x1.1 or creating US x1.2.

## Remaining work

### Phase B — governed sector evidence

Sector contribution, maximum sector weight, leave-one-sector-out and the 30%
sector cap remain deferred until Issue #366 provides an exact, source-bound
87/87 sector map. No ad hoc online classifications were used.

### Next bounded experiment

The QQQ trend overlay should be tested across all four development windows,
with the same frozen scores and no new parameter search. Required questions:

- does the drawdown benefit persist outside 2025H1;
- how much upside is lost in rapid recoveries;
- is 50% gross superior to a simple full-risk/full-cash switch;
- does the control remain positive at 40 and 60 bps;
- does the overlay reduce the canonical and revision-provider drawdowns in the
  same direction.

Any multi-window overlay candidate remains a portfolio-contract candidate, not
a model-version promotion.
