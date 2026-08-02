# US x1.1 native XGBoost grid result — 2026-08-02

## Final decision

**`data_blocked`**

The six-candidate native XGBoost experiment completed twice. Model fitting was deterministic within each frozen provider snapshot, but two full provider refreshes performed minutes apart produced different provider identities and materially different economic results. No candidate may become US x1.2 from this experiment.

### Evidence runs

| Run | Purpose | Workflow | Artifact | Artifact digest | Observed provider |
|---|---|---:|---:|---|---|
| A | initial complete grid | `30740184315` | `8831050347` | `sha256:31c5c05297bade69bb730f3df7815f043f390e2de59674db3bff151fd71d6776` | `a48bfc398b6207a0de1e38558f15caa4d096922572da2c78df636fc20aabf081` |
| B | reproducibility rerun with full provider retention | `30740473510` | `8831147387` | `sha256:67300e7d86876cd31110db9f00060b8c20a241cba93e38a7178f58eb08851e87` | `2238b2f7dc0130b536f70450992f1869a64cdbeab088623edf4eaeb59f8e6024` |

Run B is the replayable evidence package. Its artifact contains the complete Qlib provider directory: 621 provider files and all experiment outputs.

Canonical US x1.1 remains bound to:

`2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95`

Neither experimental provider matches the canonical baseline.

## What was reproducible

The following contracts were stable across both runs:

- 1,400 trading sessions from 2021-01-04 to 2026-07-31;
- 88 instruments, including QQQ;
- identical universe, features, labels, windows and portfolio conventions;
- six unique declared/effective native parameter identities;
- deterministic repeat fitting of the effective US x1.1 calibration in all four development windows;
- positive 60 bps compounded relative excess for every candidate;
- failure of every challenger to pass the drawdown gate;
- final version decision `data_blocked`.

The instability is upstream of model fitting.

## Provider instability

Between Run A and Run B:

- provider identity changed from `a48bfc…` to `2238b2…`;
- calendar and instrument contracts remained unchanged;
- 47 of 88 refreshed source CSV hashes changed again;
- changed rows retained the same dates and row counts but different file content hashes.

Affected sources included AAPL, ABBNY, ADP, AMAT, ASML, AVGO, BKNG, BKR, CEG, COST, CSCO, CTAS, EA, EME, ETN, FANG, FIX, GEHC, GOOGL, HIMX and others. The repeated changes originate from full-refresh Yahoo-adjusted source outputs, not from metadata serialization.

The experiment therefore demonstrates a stronger problem than ordinary provider drift: the current full-refresh path is not snapshot-reproducible even within the same day.

## Experiment boundary

Candidate selection used only:

- 2024H1;
- 2024H2;
- 2025H1;
- 2025H2.

The consumed 2026H1 reporting window was not loaded.

Frozen fields:

- US87 universe and QQQ benchmark;
- `momentum_volatility_volume` features;
- 10-session label, holding and rebalance;
- Top-15 equal weight;
- original score orientation;
- 20 bps base cost.

## Results by provider snapshot

Values are compounded relative excess versus QQQ at 20 bps. Drawdown is the worst development-window drawdown.

| Calibration | Run A excess | Run B excess | Run A drawdown | Run B drawdown | Stable interpretation |
|---|---:|---:|---:|---:|---|
| US x1.1 effective runtime | 114.35% | 85.07% | -33.84% | -34.11% | broad excess survives; risk remains deep |
| Lower learning rate / 300 rounds | 172.96% | 169.92% | -39.29% | -37.35% | strong return uplift; materially worse tail risk |
| Higher child weight | 113.15% | 162.08% | -38.56% | -32.19% | result ranking is provider-sensitive |
| Row and column sampling 0.8 | 164.19% | 135.80% | -33.71% | -35.01% | return uplift survives; no stable risk improvement |
| Explicit regularization | 119.93% | 137.45% | -36.61% | -34.94% | no drawdown solution; window result is provider-sensitive |
| Maximum leaves 15 | 162.09% | **177.10%** | -35.53% | -35.28% | return uplift survives; risk remains worse than baseline |

### Cost stress in replayable Run B

| Calibration | 20 bps | 40 bps | 60 bps | Positive windows | Strongest-window share |
|---|---:|---:|---:|---:|---:|
| US x1.1 effective runtime | 85.07% | 76.01% | 67.54% | 4/4 | 58.55% |
| Lower learning rate / 300 rounds | 169.92% | 156.89% | 144.42% | 4/4 | 51.49% |
| Higher child weight | 162.08% | 149.63% | 137.82% | 4/4 | 49.79% |
| Row and column sampling 0.8 | 135.80% | 124.67% | 114.67% | 4/4 | 46.62% |
| Explicit regularization | 137.45% | 126.03% | 114.83% | 4/4 | 53.44% |
| Maximum leaves 15 | **177.10%** | **164.57%** | **152.68%** | 4/4 | 46.11% |

## Gate result

No challenger passed all gates in either run.

The stable failed gate was:

> worst drawdown must improve by at least 3 percentage points versus the snapshot baseline, or remain above -22%.

In Run B, the least-bad challenger drawdown was higher child weight at -32.19%, an improvement of only 1.92 percentage points versus the Run B baseline at -34.11%. Every other challenger had a deeper drawdown than the snapshot baseline.

Transaction-cost fragility was not the binding problem. The binding problem was regime and tail risk.

## Interpretation

### 1. Parameter return rankings are not yet trustworthy

Run A ranked lower learning rate first, while Run B ranked lower leaf capacity first. Higher child weight moved from +113.15% to +162.08%, and the observed baseline moved from +114.35% to +85.07%.

These shifts are too large to treat as ordinary statistical noise because model seeds and effective parameter contracts were deterministic. The source snapshot changed.

### 2. Some qualitative parameter effects survived both snapshots

Three settings generated material return uplift in both runs:

- lower learning rate with more rounds;
- row/column sampling;
- lower leaf capacity.

However, none produced a stable drawdown improvement. They are return-seeking exploratory directions, not risk-controlled x1.2 candidates.

### 3. Parameter tuning is not the solution to the current risk problem

Across two provider revisions, every challenger failed the drawdown gate. The next research question is not “which nearby XGBoost parameter has the highest backtest return?” It is “which names, sectors and market states create the 2025H1 loss path, and can portfolio construction control it without removing the signal?”

### 4. Full provider retention is now mandatory

Run B preserves the complete Qlib provider snapshot. Future accepted evidence must include the provider data itself, not only a manifest. This allows exact replay even when public source outputs later revise history.

## Accepted learning

- Native XGBoost parameters produce genuinely distinct score and economic contracts.
- Model fitting is deterministic when the provider snapshot is frozen.
- Several nearby calibrations retain substantial excess after 60 bps costs.
- Parameter return rankings are materially provider-sensitive.
- No tested parameter configuration solves the deep development drawdown.
- Data snapshot reproducibility is the first hard gate for x1.1 growth.
- Portfolio/regime attribution should precede any wider parameter grid.

## Rejected learning

- No candidate may be called US x1.2.
- Run A or Run B cannot restate canonical US x1.1.
- The highest-return parameter cannot be selected while source snapshots are unstable.
- Row/column sampling is no longer treated as a uniquely preferred challenger; it remains one of several exploratory return-uplift variants.
- Higher child weight and explicit regularization cannot be classified from one snapshot as categorically good or bad because their window outcomes changed materially between runs.

## Next actions

1. Treat Issue #358 as the first hard blocker: distinguish source revision, adjusted-price semantics and refresh nondeterminism.
2. Use the complete Run B provider snapshot for exact replay and drawdown attribution.
3. Build the governed US87 sector map under #366.
4. Execute Issue #381 on the frozen Run B provider, comparing US x1.1 with a limited set of exploratory challengers only for mechanism attribution.
5. Execute the independent portfolio controls under #362 before any new parameter search.
6. Keep 2026H1 excluded and reserve a genuinely untouched future challenge window.
