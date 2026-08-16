# QuantSkills volume/stat alpha review — Issue #966 Phase 0–1

Status: **Phase 0 mechanism audit complete; Phase 1 native definition started; Gate 1 provider validation pending.**

This document is the handoff record for Issue #966. A new agent should read this file, the machine-readable manifest, and Issue #966 before making further changes.

## Fixed identities

- Alpha Engine base commit for this research: `52b8ec3ade1bc02f61dd6ed037c7055b32237453`.
- External research source: `quantskills/skill-quant-factor-volume-stat-alpha`.
- Pinned external commit: `b169f31106f748b8746c4c1028c162e95f7277f4`.
- External license: GPL-3.0-only.
- External source is an **idea/provenance corpus only**. No source code is copied or vendored.
- Alpha Engine US baseline remains `US x1.2`; CN baseline remains `CN x1.2`.
- No baseline model, universe, provider, label, cost, portfolio, holdout, or reporting boundary is changed by Phase 0–1.

## Phase 0 result

The source repository reports 216 factors, but the important structure is much smaller: nine base mechanisms, each represented by 24 parameter/transform variants. The local research record therefore maps the corpus at mechanism level and keeps the pinned external `factor_index.json` as the row-level source of truth instead of copying 216 rows into Alpha Engine.

| Source mechanism | Source count | Alpha Engine overlap | Phase decision |
| --- | ---: | --- | --- |
| `volume_ratio` | 24 | Directly overlaps canonical `ohlcv.liquidity.volume_vs_ma_*` | already covered; do not add |
| `volume_z` | 24 | Same volume-anomaly family, different normalization | defer until existing volume features prove insufficient |
| `dollar_volume` | 24 | Liquidity-related but adds price-scale exposure | defer; not first-wave information gap |
| `price_volume_corr` | 24 | Same mechanism already exists in package-backed Alpha158 `CORD*`; CN x1.2 already uses `qlib_alpha158.cord5` | reuse existing Alpha158 definition; no duplicate implementation |
| `obv_slope` | 24 | No current canonical/active OBV-flow factor | **first-wave new mechanism** |
| `ts_rank_close` | 24 | Same mechanism already exists in package-backed Alpha158 `RANK*` | reuse `qlib_alpha158.rank20`; no duplicate implementation |
| `ts_rank_volume` | 24 | Not required to establish the first time-series-rank mechanism | defer until price-rank ablation justifies widening |
| `ret_skew` | 24 | Not active in current US/CN baselines | later regime/risk diagnostic, not Phase 1 alpha input |
| `ret_kurt` | 24 | Not active in current US/CN baselines | later regime/risk diagnostic, not Phase 1 alpha input |

### Why the 216 source `pass` statuses are not promotion evidence

The external repository validates on a different research surface: its recorded validation is 5-day, with 98 CN and 50 US symbols. Alpha Engine's current governed models target 10 sessions on US87/CN130 with their own execution/cost semantics.

The source's `pass` status is therefore treated as formula/data/no-future validation, not proof of positive alpha. A concrete example is source factor R617 (`10d-smoothed-price-volume-correlation`): it is marked `pass` and `no_future_check=true`, while the recorded 5-day IC mean is negative and the long-short mean is approximately zero. Conversely R684 (`10d-volatility-scaled-obv-slope`) has positive external 5-day IC/ICIR. Both are only candidate priors; neither is Alpha Engine evidence.

### Gate 0 decision

**PASS at mechanism level.** There is enough incremental information to begin a narrow Phase 1, but the audit reduced the implementation scope substantially:

1. OBV/volume-flow is the only first-wave mechanism that needs a new native Alpha Engine formula.
2. Price-volume correlation should initially reuse `qlib_alpha158.cord10` for US research. CN already has the mechanism active through `qlib_alpha158.cord5`; a duplicate CN factor would add complexity without establishing information novelty.
3. Price time-series rank should initially reuse `qlib_alpha158.rank20` rather than reimplement `Rank($close,20)` under a second ID.

This is intentionally smaller than the original Issue #966 Phase 1 sketch. The audit found existing maintained definitions, so reusing them is preferable to creating parallel formulas.

## Phase 1 native candidate

The one genuinely missing first-wave mechanism is implemented independently in:

`src/factors/sets/volume_stat_research.py`

Candidate:

- `volume_stat_research.signed_volume_balance_10d`
- expression: `Sum(Sign($close-Ref($close,1))*$volume,10)/(Mean($volume,10)+1e-12)`
- required fields: close, volume
- markets: US, CN
- status: `unvalidated_formula`

This is an independent **signed-volume-flow / OBV-family proxy**, not a copy of the GPL source implementation. It measures the 10-session net signed volume change, normalized by normal volume. It intentionally uses Qlib operators already available to Alpha Engine (`Sign`, `Sum`, `Mean`, `Ref`) and avoids adding a custom cumulative-OBV evaluator or factor DSL.

It is not being added to `configs/factor_libraries/ohlcv.yaml` yet. Doing so before validation would change the canonical OHLCV catalog/source identity even though US x1.2 and CN x1.2 inputs are meant to remain frozen. If this candidate survives governed feature-quality and ablation gates, promotion should use the repository's then-current single canonical path and delete the temporary research definition rather than keep two identities.

## Resolved first-wave mechanism set

Phase 1/2 should treat the following as the three first-wave probes:

| Mechanism | Factor to evaluate | Implementation action |
| --- | --- | --- |
| OBV / signed volume flow | `volume_stat_research.signed_volume_balance_10d` | new independent research definition |
| price-volume correlation | `qlib_alpha158.cord10` for US; existing `qlib_alpha158.cord5` is already active in CN x1.2 | reuse existing canonical Alpha158 implementation |
| price time-series rank | `qlib_alpha158.rank20` | reuse existing canonical Alpha158 implementation |

Do not add transform variants yet. Do not add `ts_rank_volume`, skew, or kurtosis yet.

## Current-baseline constraints discovered during the audit

### US x1.2

US x1.2 currently uses seven canonical OHLCV factors: 5/10/20-day momentum, 10/20-day return volatility, 10-day volume momentum, and 20-day volume-vs-MA. The model target is 10-session forward return on US87. This makes all three first-wave mechanisms potentially incremental to the **active** US feature set, although two already exist in the wider Alpha158 catalog.

### CN x1.2

CN x1.2 currently uses 17 factors and explicitly includes `qlib_alpha158.cord5`. Therefore price-volume correlation is **not a new CN mechanism**. CN Phase 2 should not run a misleading `baseline + price-volume correlation` experiment that simply duplicates an already-active concept. It may later test a different CORD horizon only if that is preregistered as a within-family refinement rather than a new-mechanism ablation.

## Phase 1 tests added

`tests/test_volume_stat_research.py` records the intended contract:

- exactly one new independent definition is introduced;
- it is deterministic and remains `unvalidated_formula`;
- it contains no forward `Ref`;
- the other two first-wave mechanisms resolve from the existing Alpha158 set as `qlib_alpha158.cord10` and `qlib_alpha158.rank20`;
- no duplicate native implementation is introduced for those existing mechanisms.

These are definition/architecture tests only. They do **not** satisfy Gate 1 provider/coverage/quality validation.

## Gate 1 status

**PENDING.** The formula contract exists, but no governed-provider evaluation has yet been run for `volume_stat_research.signed_volume_balance_10d`.

Before any model ablation, the next agent must:

1. evaluate the signed-volume factor through the existing governed Qlib/provider path on the exact US87 and CN130 research-eligible periods;
2. verify coverage, warm-up, NaN/inf behavior, symbol isolation, and deterministic reproduction;
3. confirm Qlib parses/evaluates the expression on the governed provider (the operators are already part of the pinned Qlib dependency, but provider execution is the authoritative check);
4. produce a machine-readable feature-quality receipt bound to provider/universe/cutoff identities;
5. only after Gate 1 passes, open Phase 2 ablations with model family, label, portfolio, costs, and data boundaries frozen.

If the signed-volume proxy fails Gate 1, do not add a fallback engine. Either reject it or, in a separate narrow research decision, justify one alternative native formula. Do not implement classical cumulative OBV machinery pre-emptively.

## Handoff: what the next agent should not redo

- Do not re-import or locally copy the 216-factor external index.
- Do not create a QuantSkills runtime/compatibility layer.
- Do not create a second factor evaluator.
- Do not add CORD or price RANK under new factor IDs: those mechanisms already have package-backed Alpha158 definitions.
- Do not mutate US x1.2 / CN x1.2 while Gate 1 is pending.
- Do not use 2026H2 reporting/holdout data for factor selection.
- Do not interpret external 5D IC/ICIR as Alpha Engine 10D evidence.

## Next handoff checkpoint

The next durable checkpoint should be a Gate 1 feature-quality receipt plus a short Issue #966 comment containing:

- provider identity and cutoff;
- exact universe identity;
- finite/coverage statistics;
- first/last valid dates after warm-up;
- no-future/determinism result;
- pass/reject decision for the signed-volume candidate;
- whether Phase 2 can begin.
