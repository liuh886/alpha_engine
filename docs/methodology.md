# Research Methodology

> Last updated: 2026-07-29

This document is the authoritative reference for AlphaEngine's fixed-10D
research method, evidence requirements, universe-validity rules, and promotion
boundaries.

## 1. Research objective

AlphaEngine is a research-only system. Its purpose is not to maximize a single
backtest result; it is to determine whether a declared signal produces
repeatable benchmark-relative evidence after data, universe, time, cost, and
model contracts are fixed.

No current model is `trade_ready`.

## 2. Core paradigm: fixed 10D horizon

Both CN and US research use versioned specs under
`configs/research_paradigms/`.

| Market | Canonical baseline | Benchmark | Baseline universe |
| --- | --- | --- | --- |
| CN | `cn_10d_csi300_baseline.yaml` | CSI 300 (`000300`) | `cn_curated_equities_v1.yaml` |
| US | `us_10d_qqq_baseline.yaml` | QQQ | `us_curated_equities_v1.yaml` |

### Invariants

| Property | Required value |
| --- | --- |
| Horizon | 10 trading sessions |
| Holding period | 10 trading sessions |
| Rebalance cadence | 10 trading sessions |
| Economic return | `Ref($close, -10) / $close - 1` |
| Return provenance | `raw_forward_return` |
| Walk-forward policy | complete half-year OOS windows |
| Train embargo | 10 sessions |
| Research scope | `research_only=true` |

A new experiment may change an economic hypothesis, but it must not silently
change these invariants and compare the result with an earlier contract as if
the experiments were identical.

## 3. Training target and economic truth

Two return-related objects have different roles:

| Object | Definition | Allowed use |
| --- | --- | --- |
| Raw canonical 10D return | `Ref($close, -10) / $close - 1` | economic evaluation, benchmark comparison, spread and portfolio results |
| Processed rank target | same-date cross-sectional percentile rank converted to relevance gains | model fitting only |

The processed target is never a substitute for realized economic returns.
Promotion evidence, portfolio returns, drawdown, and benchmark-relative results
must use the raw canonical return.

Because the processed target is cross-sectional, changing the daily universe
changes the label, query group, feature distribution, and fitted ranker. A
point-in-time universe test is therefore a new training/evaluation problem, not
merely a filter applied after prediction.

## 4. Universe validity

### 4.1 Static curated universes

The canonical CN and US baseline specs still use static curated membership.
These universes are useful for exploratory diagnostics but have explicit
survivorship and selection bias.

- CN contains roughly 200 current A-share equities.
- US contains roughly 120 currently curated Nasdaq/NYSE equities and is not a
  historical Nasdaq-100 constituent series.

A static result must be labeled `static_curated` and cannot support trade
guidance.

### 4.2 Window-start point-in-time NDX

US model-robustness work may use
`configs/research_universes/ndx_window_start_membership.json` with:

- official Nasdaq-100 membership at the first trading day of each OOS half-year;
- the latest committed semiannual membership known on each training date;
- membership hashes bound into execution identity;
- missing historical names reported and excluded, never zero-filled or replaced
  with current constituents;
- QQQ loaded separately as a non-tradable benchmark.

Current OOS coverage is near-complete but not perfect:

| Window | Requested | Retained | Missing |
| --- | ---: | ---: | --- |
| 2024H1 | 101 | 98 | ANSS, SPLK, WBA |
| 2024H2 | 102 | 100 | ANSS, WBA |
| 2025H1 | 101 | 100 | ANSS |
| 2025H2 | 101 | 100 | ANSS |

This is window-start/semiannual PIT. It is stronger than static membership but
is not full daily/event-level PIT history.

### 4.3 Universe-validity levels

| Level | Contract | Permitted interpretation |
| --- | --- | --- |
| U0 | static curated current membership | exploratory diagnostics only |
| U1 | window-start OOS PIT plus as-of training membership | robustness research; still not trade-grade |
| U2 | event/daily PIT membership with delistings, corporate actions, aliases, and tradability | required before a universe can support trade-guidance evidence |

CN remains U0. The current NDX robustness path is U1.

## 5. Data readiness and provider lineage

Every real-data experiment must bind its provider identity and validate the
source before model interpretation.

Required checks include:

- declared date boundaries and market calendar;
- instrument identity and ticker aliases;
- duplicate dates and non-finite values;
- OHLC relationships;
- split-like discontinuities and adjusted/unadjusted mixing;
- benchmark completeness on every evaluation date;
- universe coverage and missing-symbol accounting;
- immutable repair lineage when a source is rebuilt.

The US PIT provider detected and repaired a mixed adjusted/unadjusted KLAC
history. The CN audit found 46 invalid OHLC histories on 2024-03-29; an isolated
EFinance-qfq rebuild repaired them while preserving source count and
calendar/instrument hashes.

If readiness, hash, mapping, benchmark, or minimum-window evidence is missing,
the experiment fails closed.

## 6. Walk-forward validation

Walk-forward validation uses expanding training history, a 10-session embargo,
and non-overlapping half-year OOS windows.

| Parameter | CN | US |
| --- | --- | --- |
| Requested train start | 2021-01-01 | 2021-01-01 |
| Current aligned US PIT start | n/a | 2021-04-05 |
| First complete OOS year | 2024 | 2024 |
| Complete windows currently used | 2024H1--2025H2 | 2024H1--2025H2 |
| Partial-window policy | falsification only when explicitly declared | falsification only when explicitly declared |
| Train embargo | 10 sessions | 10 sessions |

A partial window cannot compensate for failure across complete windows and
cannot independently support promotion.

### Required metrics

| Metric | Meaning |
| --- | --- |
| `mean_icir` | cross-window information coefficient stability |
| `mean_rank_ic` | mean rank-based information coefficient |
| `mean_spread` | mean top-minus-bottom cross-sectional return spread |
| `worst_drawdown` | worst portfolio drawdown across OOS windows |
| `ready_ratio` | fraction of windows satisfying all readiness gates |
| `positive_icir_ratio` | fraction of windows with positive ICIR |
| `positive_spread_ratio` | fraction of windows with positive spread |
| benchmark-relative excess | compounded strategy return relative to the declared benchmark |
| positive-excess ratio | fraction of windows beating the benchmark |

A model cannot be stable solely because IC metrics are positive. It must also
show positive benchmark-relative economics and acceptable drawdown across
windows.

## 7. Portfolio evaluation

Portfolio evidence must declare:

- Top-K and any Bottom-K diagnostic;
- weighting rule;
- holding/rebalance schedule;
- transaction-cost convention;
- benchmark mode;
- missing-return behavior;
- gross-exposure or risk-overlay rules.

Selected holdings and benchmark returns must be finite. Missing selected returns
must never be converted to zero. Bottom-K and Top-minus-Bottom results are
research diagnostics unless executable shorting assumptions are explicitly
modeled.

## 8. PromotionDecision

`PromotionDecision` is the single canonical promotion interface. It evaluates:

| Evidence | Purpose | Missing result |
| --- | --- | --- |
| `execution_identity.json` | proves the executed contract | `MISSING_EVIDENCE` |
| `data_readiness.json` | proves usable data and universe coverage | `MISSING_EVIDENCE` |
| `walk_forward_stability.json` | proves cross-window model/economic stability | `MISSING_EVIDENCE` |

Execution and promotion are separate:

| Interface | Meaning |
| --- | --- |
| execution completed/skipped/failed | technical outcome only |
| promotion status | evidence-derived research status |
| `trade_ready` | true only for a trade-guidance candidate; never an order authorization |

The retired `mean_ic > 0.1 -> DEPLOY` rule must not reappear in any consumer.

## 9. Observed-window governance

Repeatedly proposing new models after reading the same 2024H1--2025H2 windows
creates researcher overfitting even when each individual PR says “no parameter
search.”

The current complete windows are now development-observed. They may be used to:

- reproduce a frozen result;
- falsify a predeclared hypothesis;
- decompose a known failure;
- validate data or execution contracts.

They must not be used for an open-ended search over:

- technical-indicator windows;
- score orientation;
- tree parameters or boosting rounds;
- Top-K values;
- blend weights;
- gate thresholds;
- risk overlays intended only to repair an observed failure.

A new candidate must change the economic information set or earn evidence from
an untouched period, independent market, or newly valid historical dataset.

## 10. Current evidence: 2026-07-29

### 10.1 Static ranker comparison

On the as-of-2026 static curated universe:

| Candidate | Mean ICIR | Relative excess vs QQQ | Positive excess windows | Worst drawdown |
| --- | ---: | ---: | ---: | ---: |
| LightGBM LambdaRank | 0.3587 | +65.04% | 3/4 | -27.34% |
| XGBoost `rank:ndcg` | 0.3497 | +70.35% | 4/4 | -25.63% |

This is an intermediate observation only. The static universe has selection and
survivorship bias and both candidates fail the drawdown/ready-ratio gates.

### 10.2 PIT NDX robustness

The frozen comparison was rerun with the same features, target, model budget,
cost, benchmark, and portfolio contract under U1 membership:

| Candidate | Mean ICIR | Relative excess vs QQQ | Positive excess windows | Worst drawdown | Ready ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| LightGBM LambdaRank | 0.0966 | -20.49% | 1/4 | -26.11% | 0.25 |
| XGBoost `rank:ndcg` | 0.1149 | -34.08% | 1/4 | -25.59% | 0.00 |
| Historical momentum | -0.0052 | -25.70% | 0/4 | -20.17% | 0.00 |

Decision: `rejected`; no stable candidate; `trade_ready=false`.

The principal finding is that the apparent static-universe alpha does not
survive the stricter historical-membership contract. The difference between
LightGBM and XGBoost is economically immaterial relative to the universe and
drawdown problem.

### 10.3 Other stopped hypotheses

- benchmark-residual trend quality: stopped in both US and CN;
- fixed Bollinger, MACD, RSI, and close-location indicators: no cross-market
  supported candidate;
- Top-3-aligned LambdaRank objective: falsified on the declared 2026H1 partial
  holdout;
- risk overlays on the rejected static candidate: no robust cross-universe fix.

## 11. Next approved model-effectiveness work

The next task is the frozen static-to-PIT alpha decomposition described in
`docs/research/static_to_pit_alpha_diagnosis_2026-07-29.md`.

It must isolate:

- static versus PIT training membership;
- static versus PIT OOS tradable membership;
- label and score migration on common names;
- selection overlap;
- contributions from common, static-only, PIT-only, entrant, and exit groups;
- per-window and per-security concentration of the return gap.

This work explains the failure. It must not optimize the existing OHLCV ranker.
After the decomposition, a new candidate requires a genuinely new economic
information set and independent evidence.

## 12. Canonical execution

All canonical research runs through:

```text
ResearchWorkflow.run(request)
    -> SpecBoundResearchWorkflowExecutor.run_step()
    -> resolve_spec(request.market)
    -> execute_spec_bound_research(spec)
    -> execute_spec_bound_runner(spec, adapter)
    -> TRAIN -> WALK_FORWARD -> BACKTEST -> PROMOTE
                                      -> PromotionDecision
```

Free-text goals are audit metadata only and cannot silently alter the executable
spec. Unsupported markets, path traversal, spec/market mismatch, insufficient
coverage, and invalid benchmark evidence fail before model execution or
promotion.

## 13. References

| Resource | Purpose |
| --- | --- |
| `configs/research_paradigms/cn_10d_csi300_baseline.yaml` | CN fixed-10D baseline |
| `configs/research_paradigms/us_10d_qqq_baseline.yaml` | US fixed-10D baseline |
| `configs/research_paradigms/us_10d_lgbm_xgb_ranker_pit_robustness.yaml` | PIT ranker robustness contract |
| `configs/research_universes/us_curated_equities_v1.yaml` | static US exploratory universe |
| `configs/research_universes/ndx_window_start_membership.json` | U1 NDX membership evidence |
| `docs/research/static_to_pit_alpha_diagnosis_2026-07-29.md` | cause assessment and decomposition design |
| `docs/research/lgbm_xgb_ranker_comparison_2026-07-29.md` | static intermediate comparison |
| `docs/research/lgbm_xgb_ranker_pit_robustness_2026-07-29.md` | authoritative PIT decision |
| `docs/research/technical_indicator_quality_2026-07-29.md` | fixed technical-indicator decision |
| `docs/10d_universe_robustness_report.md` | maintained robustness record |
| `docs/adr/0005-promotion-decision-single-interface.md` | promotion interface |
| `docs/adr/0006-spec-bound-default-workflow-runtime.md` | canonical runtime |
| `docs/adr/0007-retire-legacy-research-runtime.md` | legacy runtime retirement |
| `src/research/promotion_decision.py` | promotion implementation |
| `src/research/spec_bound_execution.py` | spec-bound execution |
