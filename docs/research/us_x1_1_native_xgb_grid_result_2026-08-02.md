# US x1.1 native XGBoost grid result — 2026-08-02

## Decision

**`data_blocked`**

The six-candidate experiment completed successfully and every declared parameter identity was executed. However, the observed provider identity did not match the canonical US x1.1 provider, so no candidate may become US x1.2 from this run.

- workflow run: `30740184315`;
- artifact: `8831050347`;
- artifact digest: `sha256:31c5c05297bade69bb730f3df7815f043f390e2de59674db3bff151fd71d6776`;
- canonical provider: `2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95`;
- observed provider: `a48bfc398b6207a0de1e38558f15caa4d096922572da2c78df636fc20aabf081`;
- deterministic baseline repeat-fit: passed in all four windows;
- automatic model update: false.

## Provider attribution

The calendar and instrument contracts were unchanged:

- 1,400 sessions from 2021-01-04 to 2026-07-31;
- 88 instruments, including QQQ;
- identical calendar and instrument hashes.

The feature-tree hash changed because **47 of 88 source CSV hashes changed**. Changed sources included AAPL, AMAT, ASML, AVGO, COST, GOOGL, INTC, META, MRVL, MSFT, MU, NVDA, ORCL, QQQ, TSM, VRT and others. This is a source-data/provider revision, not a metadata-only difference.

The current run therefore adds a noncanonical evidence revision. It does not restate US x1.1.

## Experiment boundary

Candidate selection used only:

- 2024H1;
- 2024H2;
- 2025H1;
- 2025H2.

The consumed 2026H1 reporting window was not loaded or used.

Frozen fields:

- US87 universe and QQQ benchmark;
- `momentum_volatility_volume` features;
- 10-session label, holding and rebalance;
- Top-15 equal weight;
- original score orientation;
- 20 bps base cost.

## Aggregate result

All returns below are compounded relative excess versus QQQ across 2024H1–2025H2 on the observed noncanonical provider.

| Calibration | 20 bps | 40 bps | 60 bps | Positive windows | Worst drawdown | Strongest-window share | Mean Rank IC | Mean Top-15 overlap vs baseline |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| US x1.1 effective runtime | 114.35% | 103.96% | 94.07% | 4/4 | -33.84% | 47.82% | 0.0457 | 100.0% |
| Lower learning rate / 300 rounds | **172.96%** | **159.85%** | **147.35%** | 4/4 | **-39.29%** | 45.53% | 0.0464 | 88.3% |
| Higher child weight | 113.15% | 102.94% | 93.21% | 3/4 | -38.56% | 50.16% | 0.0435 | 90.0% |
| Row and column sampling 0.8 | **164.19%** | **152.14%** | **140.63%** | 4/4 | -33.71% | **41.86%** | 0.0450 | 90.0% |
| Explicit regularization | 119.93% | 109.01% | 98.62% | 3/4 | -36.61% | 53.58% | 0.0453 | 88.3% |
| Maximum leaves 15 | **162.09%** | **150.44%** | **139.30%** | 4/4 | -35.53% | 47.06% | 0.0459 | 83.3% |

## Gate result

No challenger passed all gates.

The common failed gate was:

> worst drawdown must improve by at least 3 percentage points or remain above -22%.

Additional failures:

- higher child weight produced negative excess in 2025H1;
- explicit regularization produced negative excess in 2025H1.

All challengers retained positive 60 bps compounded relative excess. The main problem was not transaction-cost fragility; it was unresolved regime and drawdown risk.

## Interpretation

### 1. Lower learning rate increased return but amplified tail risk

`learning_rate=0.03`, 300 rounds produced the highest compounded relative excess, but its worst drawdown deteriorated to -39.29%. Its 2025H1 excess was only +0.41%, while 2024H2 and 2025H2 supplied most of the uplift.

This is not a safer US x1.2 candidate. It behaves more like a higher-conviction return-seeking variant.

### 2. Row and column sampling is the most useful challenger

The 0.8 row/column sampling candidate combined:

- +164.19% relative excess at 20 bps;
- four positive-excess windows;
- the lowest strongest-window share, 41.86%;
- a 90% mean final Top-15 overlap with US x1.1;
- a drawdown almost unchanged from the observed baseline, -33.71% versus -33.84%.

It did not satisfy the risk gate, but it improved return and window balance without radically changing the selected portfolio. This is the strongest candidate for further attribution after the data gate is resolved.

### 3. Smaller leaf capacity also improved return, not risk

`max_leaves=15` produced +162.09% relative excess and four positive windows, but drawdown worsened to -35.53%. It changed the final Top-15 more than row/column sampling and did not solve the central risk problem.

### 4. Stronger child-weight and explicit regularization were counterproductive

Both candidates lost excess in 2025H1 and had deeper drawdowns than the observed baseline. They should not be expanded into larger grids without a new mechanism-level hypothesis.

## Accepted learning

- Native XGBoost parameters now produce genuinely different score contracts and economic outcomes.
- US x1.1 is not obviously overfit to one exact runtime; several nearby calibrations preserve or improve broad-window excess.
- Return uplift is available through lower learning rate, sampling and lower leaf capacity.
- Parameter regularization alone does not solve the 2025H1 drawdown.
- The next risk improvement should focus on portfolio/regime controls and contribution attribution, not a wider blind parameter grid.

## Rejected learning

- The run cannot support US x1.2 because the provider identity changed.
- The higher-return candidates cannot be described as superior baselines because all failed the drawdown gate.
- No conclusion from this run may overwrite the canonical US x1.1 metrics.

## Next actions

1. Freeze full provider artifacts in future evidence workflows, not only manifests.
2. Continue provider-drift attribution under #358.
3. Use row/column sampling as a named exploratory challenger for contribution and drawdown decomposition, without promotion status.
4. Complete the governed US87 sector map under #366.
5. Run the fixed-score portfolio controls under #362 on US x1.1 first; only then test whether the sampling challenger benefits from the same controls.
6. Keep 2026H1 excluded and reserve a new untouched challenge window.
