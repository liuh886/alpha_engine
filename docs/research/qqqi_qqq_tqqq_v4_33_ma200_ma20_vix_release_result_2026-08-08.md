# QQQ v4.33 MA200 slow-bear defense + MA20/VIX release — final promotion rerun

Date: 2026-08-08
Backtest cutoff: 2026-08-06 requested; last economic return in the artifact is 2026-08-05 because returns are measured adjusted-open to next adjusted-open.

Fresh evidence run: `31204072434`
Artifact: `9004000740`
Artifact digest: `sha256:7a94663c302268ab3c6fa970b41b2f306103de3dc46b714ab98c1017965601e0`

## Frozen architecture

The final joint portfolio is the frozen v4.27 Panic Repair overlay plus the v4.33 state-0 slow-bear defense:

- v4.2 formal state machine remains unchanged;
- v4.27 Panic Repair remains unchanged;
- slow-bear entry: existing QQQ SMA(200) is falling;
- strong-defense release: QQQ is no longer below existing SMA(20) and VIX is easing or normalized;
- actual strong defense: 50% QQQI / 50% SGOV;
- long-history mechanism proxy: 50% QQQ / 50% BIL;
- state 1 and state 2 allocations remain source allocations;
- close-time decision, next-session-open execution;
- 10 bps per turnover unit;
- no threshold, MA window, allocation, persistence, cooldown, or v4.27 parameter was searched in the final rerun.

## Actual QQQI / SGOV product window

Common economic window: 2024-01-30 through 2026-08-05, 631 observations. SGOV coverage 100%.

| Model | CAGR | Max DD | Vol | Sharpe | Sortino | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | 34.05% | -24.21% | 25.65% | 1.272 | 1.846 | 1.406 | 56.0 |
| v4.27 Panic Repair | 37.79% | -24.21% | 26.07% | 1.361 | 2.004 | 1.561 | 55.0 |
| v4.33 defense only | 33.08% | -21.65% | 24.23% | 1.302 | 1.856 | 1.528 | 58.0 |
| **v4.33 joint** | **36.79%** | **-21.65%** | **24.67%** | **1.394** | **2.020** | **1.700** | **57.0** |

Versus v4.2, the final joint portfolio changes:

- CAGR: **+2.73 pp**;
- maximum drawdown: **+2.57 pp improvement**;
- annual volatility: **-0.98 pp**;
- Sharpe: **+0.122**;
- Sortino: **+0.174**;
- Calmar: **+0.293**;
- turnover: 56.0 -> 57.0 units.

The actual product evidence therefore supports the joint architecture strongly: return, drawdown, volatility and all reported risk-adjusted ratios improve simultaneously.

## 2010+ QQQ / BIL mechanism window

Mechanism-only window: 2010-10-18 through 2026-08-05, 3,973 observations. BIL coverage 100%.

| Model | CAGR | Max DD | Vol | Sharpe | Sortino | Calmar | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| v4.2 | 25.72% | -38.92% | 25.79% | 1.017 | 1.446 | 0.661 | 235.5 |
| v4.27 Panic Repair | 26.51% | -39.73% | 25.90% | 1.038 | 1.480 | 0.667 | 235.5 |
| v4.33 defense only | 23.46% | -32.49% | 24.62% | 0.980 | 1.379 | 0.722 | 310.5 |
| **v4.33 joint** | **24.24%** | **-33.38%** | **24.73%** | **1.002** | **1.414** | **0.726** | **310.5** |

Versus v4.2, the final joint portfolio changes:

- CAGR: **-1.49 pp**;
- maximum drawdown: **+5.54 pp improvement**;
- annual volatility: **-1.06 pp**;
- Sharpe: **-0.015**;
- Sortino: **-0.031**;
- Calmar: **+0.065**;
- turnover: 235.5 -> 310.5 units.

This is a real trade-off, not a universal dominance result. The slow-bear defense substantially improves drawdown and Calmar, but over the long mechanism history it gives up some CAGR and slightly weakens Sharpe/Sortino because the rule is conservative in the 2010-2020 early segment.

## Chronological stability

Proxy early segment (2010-10-18 through 2020-04-06):

- v4.2 CAGR 17.74%, Max DD -27.56%, Calmar 0.644;
- v4.33 joint CAGR 13.97%, Max DD -26.89%, Calmar 0.519.

Proxy late segment (2020-04-07 through 2026-08-05):

- v4.2 CAGR 38.70%, Max DD -38.92%, Calmar 0.994;
- v4.33 joint CAGR 41.38%, Max DD -33.38%, Calmar 1.240.

The architecture is materially better in the later regime and materially more conservative in the earlier regime. This is why the original retrospective gate reports `v4_33_final_release_promising_gate_failed`: `proxy_cagr` and `chronological_calmar` fail, while actual CAGR, actual drawdown, actual Calmar, proxy drawdown, proxy Calmar, coverage, turnover and guard-year requirements pass.

## Risk interpretation

The promotion case is therefore not "v4.33 wins every metric." The case is:

1. v4.27 is the strongest return-enhancing recovery overlay but does not improve the major drawdown;
2. falling SMA200 is the only tested slow-risk selector that consistently identifies the 2022-style prolonged state-0 drawdown;
3. MA20 + VIX release prevents the slow selector from remaining defensive throughout a fast repair;
4. in the real QQQI product window the combination improves both return and drawdown;
5. in the long proxy it converts part of CAGR into materially lower drawdown while still improving Calmar.

For a formal medium-frequency risk-budget model, this is an acceptable deliberate risk/return trade-off if the model objective prioritizes controlled drawdown and Calmar over maximum unconstrained proxy CAGR.

## Promotion decision requested by owner

The repository owner explicitly requested a full backtest comparison followed by promotion of one v4.3 model.

The selected v4.3 architecture is the **v4.33 joint portfolio**:

`v4.2 state machine + frozen v4.27 Panic Repair + falling-MA200 state-0 defense + MA20/VIX release`.

The previous retrospective gate failure remains permanently recorded and is not rewritten as a pass. Promotion is an explicit portfolio-objective decision: accept lower early-history proxy CAGR in exchange for lower drawdown, lower volatility and higher Calmar, while the actual QQQI window improves on all headline dimensions.
