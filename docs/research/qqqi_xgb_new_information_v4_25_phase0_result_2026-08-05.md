# v4.25 XGBoost new-information Phase 0 result

Date: 2026-08-05  
Issue: #536  
Pull request: #538  
Decision: `new_information_phase0_no_family_admissible`

## Executive summary

v4.25 did not train another XGBoost model. It first tested whether genuinely new pre-decision information could be obtained with sufficient history, point-in-time safety, licensing clarity and fold coverage.

The final audited result is that none of the four candidate information families is currently admissible:

- the official Cboe total and equity put/call archives are valid through 2019-10-04 but have no continuous public history after that date;
- Cboe SKEW was available only as methodology/governance evidence in this contract, with unresolved numeric-history and historical-recalculation risk;
- the public FRED/ICE BofA OAS endpoints currently provide only recent history beginning in August 2023, while the model requires a 2011 start and vintage-safe use;
- no canonical, public and survivorship-safe breadth source or transparent option-positioning history was resolved.

Because no complete family passed, the code authorized no feature transformation, no future-return or path-utility calculation, no XGBoost training and no portfolio construction.

## Evidence identity

- workflow: `30942331850`;
- artifact: `8905643282`;
- artifact digest: `sha256:5d4e67f81c09106a37db174b6f43182defe8c64bfa714e8163b87ab58f8fec62`;
- contract SHA256: `36c9c815f7c2da9dcc499922978db10422f639a8bd8fae5ec5dbf2ba1fc94fb3`;
- manifest files: 8;
- independently verified hashes: 8/8;
- QQQ research calendar through: `2026-08-04`;
- normalized source availability rows: 8,090;
- rows with an available numeric observation: 8,073;
- admitted families: none.

The artifact contains observation dates, safe decision dates, value-presence flags, source identity and hashes. It does not publish the ICE numeric values and contains no outcome labels.

## Phase 0 contract

A family required all of the following before any outcome calculation:

- historical start no later than 2011-01-03;
- at least 95% coverage on QQQ decision dates after applying a conservative one-session publication lag;
- maximum unexplained gap of at most five QQQ sessions, including leading and trailing gaps;
- documented point-in-time availability;
- non-revising or vintage-safe history;
- no survivorship reconstruction or synthetic backfill;
- usable coverage in every governed fold and the 2024+ quarantine window;
- a complete indivisible family, not selected fragments.

## Source-level evidence

### Cboe total put/call archive

| Item | Result |
|---|---:|
| Raw rows | 3,253 |
| Usable rows | 3,253 |
| First observation | 2006-11-01 |
| Last observation | 2019-10-04 |
| Safe decision-date coverage, 2011-current | 56.26% |
| Maximum unexplained gap | 1,714 QQQ sessions |
| Duplicate dates | None |
| Revision classification | Non-revising archive |
| Decision | Rejected |

Fold coverage:

- 2016-2017: 503/503 sessions, 100%;
- 2018-2019: 444/503 sessions, 88.27%;
- 2020-2021: 0%;
- 2022-2023: 0%;
- 2024+: 0%.

The archive is authentic and historically useful, but it cannot support the later folds or the actual-product window. No unrelated post-2019 source was spliced onto it.

### Cboe equity put/call archive

The equity archive has the same official interval and calendar coverage:

- 3,253 usable observations;
- 2006-11-01 through 2019-10-04;
- 56.26% coverage across the governed 2011-current calendar;
- 1,714-session trailing gap;
- full 2016-2017 coverage, 88.27% in 2018-2019 and no later-fold coverage.

It was rejected for incomplete continuity, not for malformed data.

### Cboe SKEW

The configured source was methodology and governance documentation only. It supplied no immutable numeric history to the artifact. The documentation also created a methodology-change and historical-recalculation risk that was not resolved through a vintage-safe dataset.

Decision: rejected as `documentation_only_no_numeric_history`.

### ICE BofA US High Yield OAS via FRED

| Item | Result |
|---|---:|
| Raw rows | 792 |
| Usable rows | 784 |
| First usable observation | 2023-08-07 |
| Last usable observation | 2026-07-31 |
| Safe decision-date coverage, 2011-current | 19.11% |
| Maximum leading gap | 3,169 QQQ sessions |
| 2024+ fold coverage | 648/649, 99.85% |
| Decision | Rejected |

Although recent coverage is nearly complete, the source does not cover the governed development history. Its current revised history also lacks a frozen vintage contract for this study.

### ICE BofA US Corporate OAS via FRED

| Item | Result |
|---|---:|
| Raw rows | 792 |
| Usable rows | 783 |
| First usable observation | 2023-08-07 |
| Last usable observation | 2026-07-31 |
| Safe decision-date coverage, 2011-current | 19.09% |
| Maximum leading gap | 3,169 QQQ sessions |
| 2024+ fold coverage | 647/649, 99.69% |
| Decision | Rejected |

The same historical-start and vintage-safety failures apply.

### Survivorship-safe breadth

No canonical source was identified that simultaneously provided:

- authoritative daily history back to 2011;
- historical constituent or precomputed breadth integrity;
- documented close-time availability;
- public, reproducible access without reconstructing the past from current constituents.

Decision: rejected as `canonical_source_unresolved`.

### Option positioning

No transparent, reproducible historical source for dealer positioning, gamma exposure or participant-level option imbalance was available under the Phase 0 contract. Opaque vendor scores, screenshots and current-day reconstructed histories were prohibited.

Decision: rejected as `canonical_source_unresolved`.

## Family decisions

| Family | Decision | Primary reason |
|---|---|---|
| Option tail pricing | Rejected | Put/call archives stop in 2019; SKEW numeric/vintage history unresolved |
| Direct credit spreads | Rejected | Public history starts in 2023 and is not vintage-safe for the governed folds |
| Survivorship-safe breadth | Rejected | Canonical point-in-time-safe source unresolved |
| Option positioning | Rejected | Canonical transparent historical source unresolved |

The feature-overlap audit was correctly deferred because no upstream family passed source admissibility. No rejected source fragment was tested against outcomes.

## No-outcome audit

The final workflow explicitly verified:

- `outcome_calculation_authorized=false`;
- `xgboost_training_performed=false`;
- `future_returns_present=false`;
- `path_utility_present=false`;
- `action_selection_performed=false`;
- `portfolio_constructed=false`;
- exported CSV schemas contain no target, label, prediction, probability, selected state, net return or portfolio-weight columns;
- normalized availability contains no numeric `value` column.

## Combined XGBoost conclusion through v4.25

The XGBoost program has now tested three distinct boundaries:

1. v4.23 showed that nonlinear terminal-return ranking can find non-random structure but primarily learns convex endpoint action priors.
2. v4.24 removed action priors and used path-aware adjacent transitions; the existing 35 daily features then failed to predict local path utility out of sample.
3. v4.25 found no complete new public information family that satisfies the long-history and point-in-time requirements for a valid next model.

The current blocker is therefore not a missing XGBoost parameter search. It is the absence of a sufficiently long, auditable and genuinely new information set.

## Research boundary

No v4.26 model is authorized from this Phase 0 result.

Closed actions:

- splice the 2006-2019 Cboe archives to an unrelated current source;
- use current revised OAS history as if it were historical vintage data;
- reconstruct historical breadth from today's index constituents;
- use opaque dealer-gamma or positioning scores;
- train only on 2023+ and call it a replacement for the governed four-fold design;
- relax the 2011 history requirement after seeing source limitations;
- return to parameter, threshold, horizon or feature-subset tuning on v4.23/v4.24.

A future XGBoost study requires either:

- a licensed continuous Cboe/DataShop option-history dataset;
- a vintage-safe direct-credit dataset with 2011-current continuity;
- an authoritative survivorship-safe breadth archive;
- or another genuinely independent source that passes a new Phase 0 contract.

## Operating decision

- v4.2 remains the sole research baseline and Telegram signal source;
- v4.23 and v4.24 remain non-promoted historical studies;
- v4.25 authorizes no model training or shadow observation;
- Issue #348 remains unchanged;
- the XGBoost research path is paused at the data-admissibility boundary, not abandoned or falsely advanced.