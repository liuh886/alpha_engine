# US x1.0 robustness result — 2026-08-02

## Decision

`data_blocked`

The full US x1.0 backtest completed successfully on a promotion-eligible current provider, but the observed provider identity did not match the canonical US x1.0 evidence snapshot. The run is retained as a **noncanonical evidence revision** and cannot support US x1.1 or modify US x1.0.

Research only. `trade_ready=false`.

## Evidence identity

- parent model: `us_x1_0` / **US x1.0**;
- workflow run: `30736338767`;
- artifact ID: `8829711620`;
- artifact digest: `sha256:df6f1f55585e3e2a28d8bc64468d29a68314b8d88d14b520a00d93bae0e5cb80`;
- canonical provider identity: `4921168fee3afdcfb222568bed370a0273a5d8795ac57e4477184c1728384a5c`;
- observed provider identity: `edcf6ed011bfd56ea8438e9b399a34d709a36da42ea5c37388d4a4a9e0152ca5`;
- provider status: `noncanonical_provider_revision`;
- model identity: `xgb:daily_ranker:risk_controlled_momentum:gain7_round200_leaves31_leaf20_lr0.03/original`;
- effective XGBoost runtime: `rank:ndcg`, gain bins 7, 200 rounds, `max_leaves=31`, `learning_rate=0.05`, seed 42.

The legacy candidate name retains `leaf20_lr0.03`, but these two fields were not consumed by the XGBoost adapter.

## Development windows — current provider revision

| Window | Strategy | QQQ | Simple excess | ICIR | Rank IC | Turnover | Maximum drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024H1 | 19.50% | 19.42% | 0.08% | 0.0579 | 0.0246 | 7.57 | -3.63% |
| 2024H2 | 30.52% | 6.84% | 23.68% | 0.1263 | -0.0317 | 6.83 | -13.44% |
| 2025H1 | 10.88% | 7.70% | 3.18% | -0.0377 | 0.0174 | 6.90 | **-28.02%** |
| 2025H2 | 65.35% | 12.94% | 52.41% | 0.7117 | 0.1463 | 5.77 | -9.44% |

Compounded results across 2024H1–2025H2:

- strategy return: **+185.94%**;
- QQQ return: +55.20%;
- compounded relative excess: **+84.24%**.

This is materially lower than the canonical US x1.0 development evidence of +114.62% compounded relative excess. The difference must not be interpreted as model decay until provider-snapshot drift is decomposed.

## Cost robustness

The cost stress scales each window's recorded cumulative 20 bps costs linearly. It is a deterministic post-backtest sensitivity, not an order-book or market-impact simulation.

| Cost assumption | Compounded strategy return | Compounded relative excess vs QQQ |
|---:|---:|---:|
| 20 bps | +185.94% | **+84.24%** |
| 40 bps | +173.96% | **+76.53%** |
| 60 bps | +162.36% | **+69.05%** |

The model remains economically positive under the declared 60 bps stress.

## Leave-one-window-out robustness

| Excluded window | Compounded relative excess |
|---|---:|
| 2024H1 | +84.12% |
| 2024H2 | +50.82% |
| 2025H1 | +78.97% |
| 2025H2 | **+25.85%** |

Every leave-one-window-out result remains positive. However, excluding 2025H2 reduces relative excess substantially.

## Concentration and tail-risk findings

- strongest positive-window share: **66.05%** of positive simple excess, above the pre-registered 55% limit;
- worst development drawdown: **-28.02%**, below the -25% gate;
- names present in all four final Top-15 lists: **AAOI, AEHR, BE and HIMS**;
- recurring-name count: 4, below the five-name hard threshold but still economically meaningful;
- repeated exposure remains concentrated in high-beta growth, optical/semiconductor and power/AI-infrastructure names.

Final Top-15 recurrence is a selection-concentration diagnostic. It is not a complete security-contribution ledger.

## Reporting-only consumed holdout

The previously consumed 2026H1 window was reported but excluded from all decisions:

- strategy return: +120.00%;
- QQQ return: +15.51%;
- simple excess: +104.50%;
- ICIR: 0.8338;
- Rank IC: 0.1562;
- maximum drawdown: -6.71%;
- turnover: 6.10.

The changed result relative to the canonical challenge further confirms that provider identity materially affects evidence. This window cannot be reused for candidate selection.

## Provider reproducibility finding

Two full-refresh builds under the same nominal US87 scope and 2026-07-31 cutoff produced different immutable artifacts within minutes:

- workflow `30736154069`, artifact `8829643971`: provider identity `97d41b9a90fc883fd85d79f36fe777769411525cb09c1ba2a4779428acac9949`;
- workflow `30736338767`, artifact `8829711620`: provider identity `edcf6ed011bfd56ea8438e9b399a34d709a36da42ea5c37388d4a4a9e0152ca5`.

Calendar and instrument hashes were identical, but:

- provider feature-tree hashes differed;
- **47 of 88 source CSV hashes differed**;
- both refreshes used the `yfinance` source family for the affected symbols.

This is not a metadata-only provider hash change. Issue #358 must determine whether the cause is upstream adjusted-price revision, source nondeterminism, response normalization, or local build nondeterminism.

## Model-version consequence

US x1.0 remains the immutable canonical baseline documented in PR #352. This evidence revision provides useful diagnostic conclusions:

1. economics remain positive under 60 bps and all leave-one-window-out tests;
2. tail risk remains unacceptable for direct version advancement;
3. performance is too dependent on 2025H2;
4. provider reproducibility is now the highest-priority gate.

No US x1.1 candidate may be designed or promoted until provider drift is explained. After that gate, the next bounded experiment should target sector/name concentration and 2025H1 drawdown control rather than launch a broad parameter search.
