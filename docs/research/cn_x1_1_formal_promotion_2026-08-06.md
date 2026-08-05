# CN x1.1 formal promotion

Date: 2026-08-06
Model ID: `cn_x1_1`
Display name: **CN x1.1**
Source candidate: **CN x1.1 Candidate A — Regime-Gated Sector Breadth**

## Promotion decision

The authorized research candidate is promoted, by explicit user direction, to the active formal CN baseline. CN x1.0 is retained as an immutable superseded baseline; it is no longer the active CN model or a published current formal backtest.

This promotion changes publication and lifecycle status only. It does not modify the candidate's ranking score, sector construction, regime rule, rebalance interval, execution lag, costs, universe, provider snapshot, holdings, or return path.

## Frozen portfolio contract

- universe: governed static CN130 pool (`cn_selected_equities_v3`);
- active score: frozen CN x1.0 R0 raw-return ranker on `current_cn_ohlcv`;
- sector score: mean daily score percentile of each sector's Top 3 names;
- risk-on portfolio: four highest-scoring sectors, Top 1 stock per sector, equal weight;
- regime votes:
  1. CSI300 close above MA200;
  2. CSI300 60-session return above zero;
  3. at least 50% of CN130 above their own MA60;
- risk-on when at least two votes pass;
- risk-off fallback: 100% CSI300;
- rebalance: every 10 provider sessions;
- execution: one provider session after the score date;
- transaction cost: 20 bps per unit of turnover.

## Complete backtest evidence

The formal package is reconstructed from the hash-bound certified artifact, not from a new parameter search.

Evidence identity:

- workflow run: `31022910416`;
- artifact: `8937409026`;
- artifact digest: `sha256:e540e400dbefd5178122444e709182323f1b363a3c41496fd8212e5095ee5a4b`;
- provider cutoff: `2026-08-03`;
- latest fully realized 10-session holding end: `2026-07-29`;
- 102 rebalance periods;
- 252 retained target-position rows;
- 372 deterministically reconstructed weight-change transactions;
- 100 security attribution rows.

### Historical authorization window: 2022H2–2025H2

| Metric | Result |
|---|---:|
| Portfolio total return | +60.60% |
| CSI300 total return | +3.66% |
| Compounded relative excess | +54.93% |
| Maximum drawdown | -24.44% |
| Positive relative-excess half-years | 5 / 7 |
| Worst half-year relative excess | -4.24% |
| Risk-on active-sleeve hit rate | 58.97% |
| Risk-on share | 44.32% |
| Risk-on relative excess | +57.12% |
| Risk-off relative excess | -1.39% |

The risk-off relative loss is consistent with the explicit transition-cost drag of approximately 1.40%; the fallback intentionally tracks CSI300 rather than attempting active stock selection.

### Full retained path including 2026 reporting-only data

| Metric | Result |
|---|---:|
| Portfolio total return | +54.90% |
| CSI300 total return | -2.72% |
| Compounded relative excess | +59.23% |
| Maximum drawdown | -37.06% |
| Total turnover units | 54.00 |
| Transaction-cost units | 0.1080 |

The 2026 data is reporting evidence only. It was not used to alter the model or reopen selection. The larger full-path drawdown is explicitly retained rather than hidden by reporting only the authorization window.

## Published artifacts

- formal model config: `configs/models/cn_x1_1.yaml`;
- active-baseline registry update: `configs/models/model_registry_v1.yaml`;
- complete reproducible notebook: `notebooks/models/cn_x1_1_complete_backtest.ipynb`;
- formal frontend package: `data/research/formal_backtests/cn_x1_1.json`;
- formal package SHA-256: `1d2992968329efba17fc160dd4adffcfc56e8430dbcff8c0efba54588337658e`;
- deterministic promoter: `scripts/promote_cn_x1_1_formal.py`;
- retained source evidence: `data/research/cn_x1_1_regime_gated_candidate_v1/`.

The formal catalog removes CN x1.0 from the current publication set and publishes CN x1.1 in its place. The freshness contract requires CN x1.1 to remain current through the latest completed CN session before future releases.

## Release validation

The promotion PR must pass the model lifecycle contract, byte-exact formal-package reproduction, current formal-backtest integrity, repository CI, and frontend publication checks before merge. The release remains blocked if any of those checks fails or if the frozen evidence identity changes.

## Governance boundary

- `publication_status=accepted_formal_baseline`;
- `research_only=true`;
- `trade_ready=false`;
- automatic promotion remains forbidden;
- this is not authorization for brokerage execution, automated trading, or financial advice;
- CN x1.0 remains immutable and traceable as the superseded parent model.
