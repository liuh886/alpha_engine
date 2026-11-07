# US87 v6 · 261-task independent research review (2026-11-07)

**Decision:** ENGINEERING_EXECUTION_PASS / RESEARCH_SIGNAL_PROVISIONAL / PROMOTION_BLOCKED. The frozen v6 campaign ran 261/261 with 0 blocked, but this is **validation selection**, not certified Alpha or a tradable strategy. This memo audits the actual private owner-supplied final ZIP and the matching validation-comparison JSON; no vendor bars or private Checkpoint bytes are committed to GitHub.

## Evidence and identity

- Frozen batch: `us87_colab_model_search_v6_20261103`, `run_id=c027ba478d4386d943ccdd8e960ce733b0744349acb4ed9190a1cf89e57d5f0b`.
- v6 source ZIP SHA256 `b4745e46fc26b0328e22de50e579ebbf1d400996258ea6ebb43c1ff739ed5a1a`; manifest SHA256 `4f8225f3c68ee0886b9b707ca140e91dcb509b739b8548fdc10f258574d3da1a`; runner `0c8152496ebeeed559ceab9b095594501fca516b`.
- Final private checkpoint `e2-us87-v6-checkpoint-20261106T170336967106Z-e4a6c8aa.zip`, archive SHA256 `0b209944f3fa3219ce4bad03f7ed2b5b2e203fb097697d46bca608c9852bb5a9`, indexed-file manifest SHA256 `eb3b720ffc64e5cc62ace5295adef357559bab0074eddb45bc224ed028ef306f`; 784 index entries checked, 261 distinct trial wrappers and study receipts, all ready.
- Evidence: private Drive `AlphaEngine/03_Data/Research_Exchange_P2/incoming_unreviewed/us87-v6-price-repair-0c8152496e/`, corresponding `research_reports/20261106T170349394542Z-validation-comparison-v6.json`. Immutable original v5 is NOT a valid comparison baseline after discovered KLAC/CRWD price contamination.
- 29 configurations: 24 search, 1 momentum rule, 3 feature ablation/control, 1 cost stress; 3 chronological folds × 3 seeds. **The correct observational unit for paired comparisons is the temporal fold**, not 261 independent samples.

## Fold-aligned research results (net excess vs QQQ, percentage points)

| Strategy | Fold A (2026-01-02—02-27; 39 sessions) | Fold B (2026-03-02—04-30; 43) | Fold C (2026-05-04—06-30; 40) | Median net excess | Worst fold drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| QQQ-relative 20-day momentum | +50.30 | +13.25 | +19.81 | +19.81 | -30.41 |
| XGBoost p06 | +48.64 | +18.81 | +48.20 | +48.20 | -23.41 |
| XGBoost p03 | +41.15 | +60.72 | +19.95 | +41.15 | -22.77 |
| LightGBM p03 | +33.04 | +34.29 | +37.95 | +34.29 | -25.89 |
| LightGBM p08 | +27.02 | +31.91 | +37.00 | +31.91 | -21.43 |

**Important estimator distinction:** subtracting two standalone medians (48.20 − 19.81 = **28.39 pp**) does **not** measure the typical paired increment of p06 over momentum. Its same-fold deltas are **-1.66, +5.56, +28.39 pp**, with paired median **+5.56 pp**. The top model **loses to momentum in Fold A**. LightGBM p03's same-fold deltas are -17.26, +21.04, +18.14 pp; paired median +18.14 pp. Three short, linked folds cannot establish a stable superiority distribution or statistical significance.

- p06 is the top configuration **under the predeclared validation median metric**, with rank IC median **0.0544** and worst fold drawdown **-23.41%**. Its p06 volatility feature gain share rose from 34.35% (A) to 66.93% (B) and 60.76% (C). This makes risk/volatility dependence, exposure concentration and regime-specific attribution a priority. Gain importance **is not** a causal explanation.
- p03 (XGB) is more fold-dispersed; LightGBM p03 is more uniform across the three folds, but lagged the momentum rule in Fold A. Keep **p06 and LGB p03** as research challengers, not as promoted model versions.
- The rule baseline and search models report substantial short-window QQQ-relative excess, including 50.30 pp for the rule in Fold A. The curated US87 universe, top-5 concentration and short 39/43/40-session OOS intervals can explain strong headline outcomes without a generalizable cross-market edge. Review constituent exposures and underlying day-level capital/turnover before inferring performance quality.

## Ablation and cost stress (matched control, not selected winner)

| Variant | Fold A | Fold B | Fold C | Median |
| --- | ---: | ---: | ---: | ---: |
| XGB control/full | 35.70 | 18.46 | 12.22 | 18.46 |
| XGB momentum-only | 32.47 | 28.13 | 15.55 | 28.13 |
| XGB risk/liquidity-only | 14.22 | 40.07 | 30.02 | 30.02 |
| XGB *control* at stress cost | 32.40 | 14.41 | 8.65 | 14.41 |

- At **3 bps cost + 5 bps slippage** (control) versus **10 + 15 bps** (stress), paired control-minus-stress deltas are **+3.30, +4.05, +3.57 pp**, median **+3.57 pp**. Difference of the two standalone medians is +4.05 pp and is **not** the paired median. This stress applies to the control configuration, **not p06**; p06 requires its own matched cost curve.
- Momentum-only and risk/liquidity-only models sometimes beat the full control, contradicting any claim that all four features have demonstrated incremental value. This is an **ablation diagnostic**, not a controlled proof of feature causality.

## Seed repetition, throughput and scope

- All 29 × 3 = **87 configuration/fold groups** have exactly one distinct observed (net excess, drawdown, Rank IC) performance vector across their three declared seeds. Thus **174 of 261 training executions add no distinct observed performance outcomes**. This is not a blanket right to delete seeds: next-generation trials must prove deterministic equivalence at effective model/feature spec level before coalescing work.
- Frozen training uses CPU XGBoost `hist`, fixed structural parameters (default subsample and colsample at 1), and LightGBM with `deterministic=True` / `num_threads=2`. Multiple seeds can therefore produce identical portfolio metrics; confirm numerical/receipt equivalence before deduplication.
- Sum of per-trial wall timers: **40.17 minutes** (XGB group 22.98, LightGBM 16.08, momentum 1.11); this does **not** measure end-to-end notebook wall clock, memory, CPU utilization, cloud Compute Units or reproducible speedups. CPU parallelization and shared feature materialization require measured benchmarks.
- All 87 candidates + QQQ share 292 sessions from 2025-06-05 to 2026-08-04, with 20-session features and 5-session forward targets. Fold train samples grow 114 → 154 → 197 effective sessions. Three folds are disjoint OOS dates but share expanding history, universe and research decisions.
- The private receipts do **not** provide complete daily holdings, realized trades, turnover/volume participation, per-symbol alpha attribution, bid/ask slippage or source-vintage PIT evidence. Such quantities **cannot be reconstructed faithfully** from the JSON aggregate; do not fill gaps with estimates.
- Explicit boundaries: `research_only=true`, `trade_ready=false`, `pit_certified=false`, `holdout_evaluated=false`, final 2026-07-01—08-04 holdout prior-consumption status `NOT_CERTIFIED`. Selected retrospective US87 constituents introduce possible survivorship and selection bias.

## Research continuation gates

1. **P0: Benchmark validity.** Pair each configuration's returns with the **same-fold 20-day momentum** and QQQ; report fold-level deltas, IC, drawdown and bootstrapping only after obtaining day-level non-overlapping evidence. No standalone-median subtraction as uplift.
2. **P0: Trace and risk.** Persist a private daily portfolio ledger for p06, LGB p03, the fixed momentum baseline and the control under identical execution/cost assumptions; verify securities, exposure, contribution concentration, daily returns, turnover and capacity. The ledger must be generated by the evaluator, not simulated from summary fields.
3. **P0: Leakage/selection review.** Document purged/embargoed forward-label training dates, price-adjustment vintages, curated-universe membership construction, vendor source timing, split repair and research decisions. Preserve `NOT_CERTIFIED` holdout until prior non-consumption is proven; if that cannot be established, freeze a **genuinely later, new untouched forward period** before any next model selection.
4. **P1: Focused studies.** Explicitly run matched p06 cost scenarios (including zero, base, stressed levels), a momentum baseline with comparable top-k and turnover assumptions, volatility/sector-neutral exposure diagnostics, seed-equivalence proof, and a new independent period. Avoid expanding the hyperparameter grid before these checks.
5. **Decision gate.** No production or trading integration until a distinct evaluation can support a stable paired advantage net of costs, coherent exposure explanations, and adequate PIT/universe provenance. In the meantime retain p06 and LGB p03 as challengers.

**Review disposition:** **RESEARCH_SIGNAL_PROVISIONAL; MODEL_PROMOTION_BLOCKED**. Execution and evidence integrity are distinct from independent financial efficacy.


## Independent local verification after Owner completion (PR #1380)

The local Agent independently copied the exact Owner final ZIP/comparison to a
fresh private namespace, checked the externally recorded archive/index SHA256s
and ZIP CRC, and ran the frozen0c8152496e canonical restore against verified v6
inputs offline:784files restored,261study/spec/wrapper and inner hashes valid,
0blocked. Locally reconstructed train/test/inference-context data hashes match
**all261cloudstudies**, as do QQQ fold returns. No new model was fitted; complete
model-level cross-platform parity and a real fresh-Colab-session restart remain
unobserved. The original price package, checkpoint files, recovery tip and source
comparison were not modified.

The initial postrun reviewer accepted deliberately falsified comparison copies:
NaN aggregate, a duplicated search ranking, or the removal of FoldC from every
config. These acceptance holes are fixed, with source/spec/study-inner-hash,
comparison/config identity, full fold coverage, seed/window comparability,
finite-value, ranking order and bounded ZIP checks. Unpinned review is labelled
internal integrity only. Original actual findings remain unchanged. **72focused
regressions/Ruff/MypyPASS**; raw evidence stays private.

A copied saved notebook output records Python3.12.12,2logicalCPUs and locked
NumPy1.26.4/Pandas3.0.1/SciPy1.17.1/XGBoost3.2.0/LightGBM4.6.0. The2410.3474s
sum is whole-task wall time, not fit-only CPU or end-to-end notebook time. There
is still no measured peak Colab RAM, actual CPU utilization, Compute Units bill
or cache/GPU benefit. Do not infer these values from the task timer sum.

The same-fold p06 paired median remains+5.56pp; scientific status remains
PROVISIONAL and promotionBLOCKED. Cache benchmarks, R2workers and the E4RFC
were not executed in this review. Daily attributable portfolio evidence,
winner-matched cost stress and independent eligible OOS still precede promotion.

See [machine-readable acceptance and private delivery](../evidence/us87_v6_colab_review_2026-11-07/README.md).
