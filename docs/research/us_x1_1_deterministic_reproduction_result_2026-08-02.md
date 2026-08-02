# US x1.1 deterministic reproduction result — 2026-08-02

## Decision

**`us_x1_1_deterministic_on_revision_provider`**

The exact effective US x1.1 contract was fitted independently twice for every
complete development window on deterministic raw-adjustment provider
`5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95`.

Run A and Run B matched exactly on:

- effective parameter identity;
- complete score-ledger SHA-256;
- deterministic rank-ledger SHA-256;
- complete per-rebalance Top-15 selection-ledger SHA-256;
- raw 10-session return identity;
- 20, 40 and 60 bps metric identity;
- aggregate economics.

This proves model execution is deterministic on the frozen data revision. It
does not replace canonical US x1.1, create US x1.2 or imply trade readiness.

## Evidence identity

- Issue / PR: #393 / #394;
- workflow run: `30743067256`;
- artifact: `8831960659`;
- artifact digest:
  `sha256:4fa4811812cba5c231edf703281944e0153dfcad672aa47a8924251d48d1f831`;
- source provider artifact: run `30742690159`, artifact `8831837784`;
- provider identity:
  `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95`;
- effective model identity:
  `c45831d096e5da0d8e0fe15762ec29c949d69ff9d6dfc022fa7f6244b5e6ec0d`.

## Frozen contract

- exact `us_selected_equities_v2` and QQQ reference;
- `momentum_volatility_volume` features;
- XGBoost `rank:ndcg`;
- gain7 target;
- 200 boosting rounds;
- `max_leaves=31`, `max_depth=0`;
- `learning_rate=0.05`, seed 42;
- Top-15 equal weight;
- 10-session label, holding and rebalance;
- 20 bps base cost;
- candidate-selection windows limited to 2024H1–2025H2;
- 2026H1 excluded as consumed evidence.

No feature, parameter, universe, cost or portfolio search occurred.

## Per-window deterministic receipts

The SHA-256 values below were identical in Run A and Run B.

| Window | Score | Rank | Top-15 ledger | Metrics |
|---|---|---|---|---|
| 2024H1 | `e90b7d301d6487f8f5c858006b4e5dfc2bb837c63f8b6cd7dba4faf7556aed89` | `5d2dd897253dfab4592f67e3214d5f1d2a11d6aaf31ec52a6cd34ebe34b678e6` | `98d7c37d687a8dd863a5ad2f3f458ea28ad45e28d3d4f734843100d0f268e5dd` | `0156de2bd2cf3a829c98617828904b191a3dff239b3da4fa91e19398fbf54c07` |
| 2024H2 | `f0af377afa17d8c55e4f7dee8770e7f24794a77c9dcaf91a322b9b1ebef7c061` | `b4b0747498e8854688365b41a1e2c868c499dbbe44a4bf325434268c98b507de` | `bf64265a95f448630210e498594cff6fc59bcb26f0560ed7646c82dbdd3873b6` | `db523279104c1c8a65f8054ff983be82bda4cc108b04de027c959704925f5953` |
| 2025H1 | `3e4390f38615118ab3ae0218e0d4df7855a82654b829584db47520685b7b0301` | `d3311383c9984a50056ec473d3cf929c33e56f0ef01c230cc8a7f5ffb194cc8b` | `77957781a80f51811a2c099271e86aa30939c0c7c9608cbc38c32f6d28205ffd` | `db2b04208969fea8c9aa350724b4cca149442886fb940b031816097b54f96979` |
| 2025H2 | `121bcd1fdd8a59f1f51df5bb60dfbb021ea88b1176b66611018b1779b2150ec2` | `76f2af7e78641826b4ffa41da74aef2f688312071a562a93789eef70f6f5a6ba` | `20e0cc81d37c9e5a74d90a39a529961bc1f58077b92d6efa2857bd37b4f006a5` | `d236a049c0f1764bfbe5b57deb8a619237826a38083f82ad69629356ec0919df` |

The corresponding raw-return identities were also identical between runs.

## Revision-provider economics

| Metric | Result |
|---|---:|
| Compounded strategy return, 20 bps | +231.11% |
| Compounded QQQ return | +55.20% |
| Compounded relative excess, 20 bps | +113.35% |
| Compounded relative excess, 40 bps | +102.96% |
| Compounded relative excess, 60 bps | +93.07% |
| Positive-excess windows | 4/4 |
| Mean ICIR | 0.2599 |
| Mean Rank IC | 0.0459 |
| Mean top-minus-bottom spread | 0.02938 |
| Worst drawdown | -33.88% |
| Strongest positive-window share | 48.72% |
| Names in every final Top-15 | AAOI, BE, TYGO |

The signal remains cost-robust. The primary weakness is tail and regime risk,
not transaction-cost sensitivity.

## Canonical versus deterministic revision

Canonical US x1.1 remains bound to provider
`2e903b716fd6933ecc2194f60b922322ebe57f1b2c8751a244c871ad27a92b95`.

| Metric | Canonical US x1.1 | Revision provider | Change |
|---|---:|---:|---:|
| Compounded relative excess, 20 bps | +110.44% | +113.35% | +2.91 pp |
| Worst development drawdown | -27.15% | -33.88% | -6.72 pp |
| Mean ICIR | 0.2280 | 0.2599 | +0.0320 |
| Mean Rank IC | 0.0410 | 0.0459 | +0.0049 |
| Recurring names | AAOI, AEHR, BE | AAOI, BE, TYGO | changed |

### Window-level change

| Window | Canonical excess | Revision excess | Change | Canonical DD | Revision DD |
|---|---:|---:|---:|---:|---:|
| 2024H1 | +6.10% | +11.75% | +5.65 pp | -4.16% | -6.87% |
| 2024H2 | +40.14% | +32.37% | -7.78 pp | -9.91% | -13.97% |
| 2025H1 | +8.98% | +5.54% | -3.44 pp | -27.15% | -33.88% |
| 2025H2 | +38.77% | +47.19% | +8.42 pp | -13.59% | -19.38% |

The migration does not eliminate the 2025H1 problem. It makes the same weak
regime more severe. Higher aggregate excess therefore cannot be interpreted as
an improved baseline.

## Evidence limitation

The canonical US x1.1 model card retains window metrics and final Top-15 lists,
but the original artifact does not retain complete score and per-rebalance
selection ledgers in the same new contract. Therefore:

- full canonical-versus-revision score-rank correlation cannot be reconstructed;
- complete historical selection overlap cannot be reconstructed;
- no missing curves or ledgers were inferred.

This limitation does not affect the exact Run A/B determinism proof on the new
provider.

## Accepted learning

- The raw-plus-adjustment provider contract produces deterministic model inputs.
- The effective XGBoost US x1.1 runtime is exactly reproducible on that provider.
- Tiny historical adjustment revisions can materially change portfolio paths and
  drawdowns even when aggregate excess is similar.
- Provider revision identity must remain part of every model result.
- The 2025H1 weakness is structural enough to persist and worsen across the data
  revision.

## Rejected learning

- The revision provider does not replace canonical US x1.1.
- The +2.91 percentage-point excess improvement does not justify promotion.
- No US x1.2 candidate is created.
- 2026H1 remains consumed and unavailable for candidate selection.
- Deterministic execution is not equivalent to acceptable portfolio risk.

## Next research

Proceed to Issue #381 on this frozen provider and retained ledgers:

1. identify the exact 2025H1 peak-to-trough path;
2. calculate name and rebalance contribution;
3. measure recurring-name and volatility/beta concentration;
4. distinguish shared-loss selections from rank-migration losses;
5. test each pre-registered portfolio control independently under #362;
6. preserve US x1.1 model scores and parameters unchanged.
