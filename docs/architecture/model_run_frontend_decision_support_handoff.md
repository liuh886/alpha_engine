# Model-run frontend and decision-support handoff

Status: proposed implementation sequence
Related issue: [#434](https://github.com/liuh886/alpha_engine/issues/434)
Baseline revision: `3f353ff03b78ed022d55b8299464afbdf84c5156`
Boundary: `research_only=true`, `trade_ready=false`

## 1. Purpose

Issue #434 completed the freshness, reproducibility and public-origin acceptance
foundation for the three accepted formal backtests. The next program should make
that foundation reusable for every governed model iteration and turn the
frontend from a collection of evidence views into a research decision-support
workspace.

This document is the implementation handoff. It deliberately decomposes the
work into reviewable pull requests so strategy experiments, provider work and
frontend improvements can continue in parallel without weakening the formal
publication boundary.

## 2. Current state

The current release has several strong properties:

- the formal catalog is an explicit allow-list;
- package and catalog hashes are verified before publication and again in the
  browser;
- stale formal evidence fails closed;
- the public site exposes performance, holdings, trades, attribution and
  evidence-completeness states;
- local directories, file sets and ZIP bundles can be opened without upload;
- missing evidence is generally shown instead of reconstructed.

The current path is nevertheless model-specific:

```text
model workflow
  -> model-specific source archive
  -> scripts/build_formal_model_backtests.py
  -> one monolithic formal JSON package
  -> formal_backtests/catalog.json
  -> build-time copy
  -> browser parser and ModelData normalization
  -> Backtests / Models / Compare views
```

The principal gaps are:

1. `scripts/build_formal_model_backtests.py` contains separate hard-coded
   extraction logic for the three currently published models.
2. The formal catalog cannot also serve as a history of ordinary governed model
   iterations without weakening its accepted-baseline meaning.
3. Metric names are free-form strings. The three packages use different names
   and availability semantics for annualized return, excess return, turnover,
   IC and risk metrics.
4. Frontend surfaces read different projections of the same model. A formal
   trade ledger can appear in Backtests while Models reports that no
   signal/execution ledger exists.
5. `AttributionInterpretation` reconstructs contributions from positions and
   prices and can describe a rules-based ETF rotation model as demonstrating
   stock-picking ability. Formal evidence views must not create a second
   attribution authority in the browser.
6. Generic metric cards can render `Ann: null` and `IR: null` when fields are
   absent rather than explicitly null.
7. Models, Backtests and Compare partially duplicate selection and comparison
   responsibilities.
8. Wide selector and window tables do not reflow well at the production desktop
   viewport and will become harder to use as the run count grows.
9. The frontend presents results but does not yet expose a manifest-bound
   supported/not-supported/blocked decision, the evidence for and against it,
   or the next permitted validation step.

## 3. Target architecture

The durable artifact contract is the interface between Python research code and
the static frontend. A connected HTTP application is not required.

```text
governed model run
  -> generic Model Run Bundle v2 exporter
  -> schema, identity and evidence validation
  -> one of three publication channels
       local: directory or ZIP
       preview: branch-scoped governed iterations
       formal: accepted named baselines only
  -> channel catalog
  -> one frontend loader and one normalized domain model
  -> Runs / Review / Compare / Decisions
```

The publication channels have different visibility but the same package
contract:

| Channel | Purpose | May contain | Must not imply |
| --- | --- | --- | --- |
| local | immediate review of a workstation run | valid local run bundles | repository acceptance |
| preview | CI-validated branch research | candidates, failures, diagnostics | formal promotion |
| formal | public accepted evidence | accepted named baselines | trade readiness |

The existing `formal_backtests/catalog.json` remains the formal allow-list.
A new `model_runs/catalog.json` indexes non-formal governed iterations. The
frontend makes the active channel and publication status visible at all times.

## 4. Model Run Bundle v2 outline

Each run receives immutable identities:

- `model_family_id`: stable research family;
- `model_version_id`: frozen model and portfolio contract;
- `run_id`: one execution of that version;
- `bundle_id`: content-bound exported evidence identity.

The manifest indexes content-addressed sections instead of embedding every row
in one document:

```text
manifest.json
summary.json
performance.json
risk.json
robustness.json
portfolio.json
trades.json
attribution.json
diagnostics.json
lineage.json
decision.json
```

Every section declares SHA-256, byte size, media type, availability and whether
it is required for the declared model kind. The frontend loads `manifest` and
`summary` first and fetches heavy ledgers only when their views are opened.

Model kinds are a discriminated union rather than a generic label:

- `rules_based_allocation`;
- `cross_sectional_ranker`;
- `forecast_model`;
- additional kinds only through a reviewed schema extension.

Views and required evidence follow `model_kind`. A rules-based allocation model
must not receive stock-picking language; a ranker must not receive state-machine
interpretation merely because both export positions.

Canonical metrics use stable IDs rather than display labels. A metric contains:

```text
metric_id
value
unit
direction
estimator
annualization
sample_count
scope
availability_status
unavailable_reason
```

Missing states are distinct:

- `not_applicable`;
- `not_computed`;
- `not_retained`;
- `blocked_by_source`;
- `available`.

## 5. Pull-request sequence

### PR 0 — this handoff

Suggested title: `docs: hand off model-run frontend decision-support program`

Purpose:

- record the inspected current state;
- define the target artifact boundary;
- assign small, ordered implementation units;
- prevent later PRs from mixing contract, migration, UX and decision semantics.

Acceptance:

- documentation-only diff;
- current production behavior remains unchanged;
- downstream PRs can cite a stable scope and dependency sequence.

Must not include:

- model selection changes;
- frontend behavior changes;
- new publication status claims.

### PR 1 — repair frontend evidence trust

Suggested title: `fix: make formal model evidence semantically consistent`

Purpose:

- remove misleading or contradictory claims before expanding the model catalog.

Required work:

1. Fix absent metric handling so `undefined` never renders as `Ann: null`,
   `IR: null` or another stringified null state.
2. Remove client-derived formal attribution from
   `AttributionInterpretation`. Formal pages render the retained formal
   attribution rows or an explicit unavailable state.
3. Introduce a small `model_kind` adapter for the existing three models so ETF
   rotation never receives stock-picking copy.
4. Make Models, Backtests and Compare consume the same formal trade,
   attribution, cost and snapshot projection.
5. Read costs from `formal.portfolio_contract` instead of the unrelated legacy
   parameter path.
6. Give unavailable metrics a reason rather than a bare dash or `N/A` where the
   source already declares that reason.
7. Fix selector and evidence-table reflow at the production desktop and Pixel 7
   acceptance viewports.

Likely files:

- `qlib-dashboard/src/components/OverviewCards.tsx`;
- `qlib-dashboard/src/components/AttributionInterpretation.tsx`;
- `qlib-dashboard/src/components/Dashboard.tsx`;
- `qlib-dashboard/src/components/ModelSelector.tsx`;
- `qlib-dashboard/src/pages/EvidenceModelsPage.tsx`;
- `qlib-dashboard/src/pages/ComparePage.tsx`;
- `qlib-dashboard/src/lib/formal-backtest.ts`;
- associated unit and browser tests.

Acceptance:

- no visible stringified null metrics;
- no client-created stock-picking claim for QQQ Rotation v4.2;
- a formal trade ledger has the same availability on every model surface;
- all three packages expose correct cost and completeness states;
- selector and core tables do not lose required controls at supported widths;
- frontend unit, static PWA and public-origin fixture tests pass.

Must not include:

- Bundle v2;
- catalog redesign;
- new model metrics or improved backtest results.

Dependencies: PR 0 only.

### PR 2 — define Model Run Bundle v2 and canonical metrics

Suggested title: `architecture: define model run bundle v2`

Purpose:

- establish one stable, extensible interface before replacing builders or
  redesigning pages.

Required work:

1. Add `MODEL_RUN_BUNDLE_V2.md` and JSON Schemas for manifest, catalog, metric,
   section availability and decision receipt.
2. Define the four immutable identities and their hash bindings.
3. Define publication-channel and publication-status enums without weakening
   the formal catalog.
4. Define the `model_kind` discriminated union and required/optional sections.
5. Define canonical metric IDs, units, direction and unavailability reasons.
6. Define a `comparability_key` covering market, universe, benchmark, date
   interval, trace frequency, horizon, rebalance and cost contract.
7. Add Python and TypeScript contract fixtures and cross-language tests.
8. Document one additive v1-to-v2 compatibility period; no second permanent
   frontend domain model.

Acceptance:

- invalid identities, hashes, publication boundaries and metric units fail
  closed;
- Python-generated fixtures parse in TypeScript;
- every existing v1 formal package has a documented v2 mapping;
- no current v1 production package or catalog changes in this PR.

Must not include:

- the generic exporter implementation;
- page redesign;
- removal of v1 code.

Dependencies: PR 1 should be merged or its stable projection decisions adopted.

### PR 3 — generic exporter, adapter registry and run catalogs

Suggested title: `refactor: export governed model run bundles generically`

Purpose:

- allow any model workflow to produce the same frontend-readable result without
  editing one central model-specific script.

Required work:

1. Create a generic exporter that writes Bundle v2 sections atomically.
2. Move source-specific extraction into small registered adapters with explicit
   input contracts.
3. Produce `model_runs/catalog.json` for local/preview iterations while keeping
   `formal_backtests/catalog.json` as the accepted-baseline allow-list.
4. Validate catalog order, duplicate identities, hashes, section availability,
   research boundary and channel rules.
5. Integrate the exporter into reusable workflow steps so another agent can add
   a model adapter without modifying the frontend.
6. Add deterministic reproduction and unchanged-input idempotency tests.
7. Keep failures and rejected candidates in preview evidence when declared; do
   not silently omit them.

Acceptance:

- one fixture for each existing model kind exports through the generic path;
- byte-identical inputs generate byte-identical bundles;
- preview records cannot enter the formal catalog;
- an adapter cannot omit a required section without a machine-readable blocker;
- unrelated research workflows remain path-scoped and non-blocking.

Must not include:

- a visual redesign;
- automatic promotion;
- an HTTP mutation service.

Dependencies: PR 2.

### PR 4 — unified frontend loader and information architecture

Suggested title: `feat: load governed model runs across publication channels`

Purpose:

- make every governed iteration discoverable while keeping formal baselines
  visually and semantically distinct.

Required work:

1. Add one Bundle v2 loader with boundary validation, hash verification and
   lazy section loading.
2. Retain a single temporary v1 adapter for the three existing formal packages.
3. Add channel-aware run discovery: local, preview and formal.
4. Replace the current overlapping navigation with:
   - `Runs`: searchable iteration catalog;
   - `Review`: one run's evidence;
   - `Compare`: compatible run comparison;
   - `Decisions`: reserved until PR 6;
   - existing Data, Factors, Reports and Methodology evidence.
5. Add filters for model family, version, market, date, publication status,
   evidence status and verdict.
6. Preserve selected run/version/channel in a deep-linkable URL.
7. Load summary first and performance, trades and attribution only on demand.
8. Provide compact responsive selection cards instead of a fixed wide table.

Acceptance:

- a newly indexed preview bundle appears without frontend code changes;
- formal and preview records cannot be visually confused;
- local folder/ZIP loading uses the same normalized domain object;
- broken optional sections do not hide a valid summary, while required-section
  failures remain fail-closed;
- keyboard, desktop and mobile selection flows pass.

Must not include:

- new statistical claims;
- decision recommendations;
- removal of v1 compatibility.

Dependencies: PR 3.

### PR 5 — Alpha, risk, robustness and portfolio review

Suggested title: `feat: expose complete model capability evidence`

Purpose:

- organize evidence around the questions a researcher must answer before
  continuing or stopping a hypothesis.

Required work:

1. Add a Summary view with identity, cutoff, evidence status and authoritative
   result boundaries.
2. Add an Alpha view with strategy, benchmark and excess paths; rolling evidence
   only when the package retains sufficient frequency.
3. Add Risk with drawdown depth/duration, volatility, concentration, turnover
   and declared tail evidence.
4. Add Robustness with window distribution, regime evidence, cost sensitivity
   and failures where retained.
5. Add Portfolio with holdings changes, signal/execution separation, cost drag
   and concentration.
6. Make model-kind-specific sections explicit:
   - allocation state and transition evidence for rules-based allocation;
   - IC, rank IC, spread, decay and cross-sectional exposure for rankers;
   - calibration and forecast-error evidence for forecast models.
7. Make every displayed claim link to its source section and scope.
8. Provide accessible tabular alternatives for charts and avoid color-only
   comparison states.

Acceptance:

- no chart or narrative is rendered when its required evidence is unavailable;
- different trace frequencies are visibly distinct;
- incompatible runs receive descriptive side-by-side review but no winner
  highlight or causal comparison;
- partial evidence uses compact reasoned states rather than sparse fabricated
  tables;
- all claims expose source, scope and computation semantics.

Must not include:

- client-generated investment advice;
- reconstructed missing data;
- decision verdict generation.

Dependencies: PR 4.

### PR 6 — manifest-bound research decision support

Suggested title: `feat: publish and review research decision receipts`

Purpose:

- upgrade the product from evidence visualization to research decision support
  without presenting trading instructions.

Required work:

1. Generate `decision.json` from the governed evidence process, not from browser
   heuristics.
2. Support `supported`, `not_supported` and `blocked` verdicts.
3. Bind every gate and claim to source artifact paths and hashes.
4. Include supporting evidence, contradictory evidence, blocked gates,
   interpretation limits, failure modes and one next permitted validation step.
5. Add a Decisions workspace and a run-level decision summary.
6. Clearly distinguish absent decision, pending review and completed verdict.
7. Keep all actions research-oriented: refresh evidence, inspect a failed gate,
   run a predeclared validation or stop a hypothesis.

Acceptance:

- the browser cannot strengthen or synthesize a verdict;
- a missing or hash-mismatched source invalidates the affected claim;
- failed and blocked decisions remain visible research memory;
- no decision view uses buy, sell, order, allocation instruction or trade-ready
  language;
- decision receipts are reproducible and covered by public-origin tests.

Must not include:

- broker integration;
- automated promotion;
- LLM-generated unbound conclusions.

Dependencies: PR 5 and the backend evidence decision contract.

### PR 7 — migrate formal baselines and retire v1 debt

Suggested title: `refactor: migrate formal baselines to model run bundle v2`

Purpose:

- complete the transition after the v2 path has proven equivalent in preview.

Required work:

1. Reproduce QQQ Rotation v4.2, US x1.1 and CN x1.0 as Bundle v2 without
   changing their frozen parameters, universes or accepted evidence.
2. Byte/hash-bind the migrated sections to the same immutable source archives.
3. Verify UI parity and explicitly review intentional presentation changes.
4. Move formal publication to the generic exporter.
5. Remove the model-specific builder and the temporary frontend v1 adapter only
   after all accepted packages and rollback fixtures are migrated.
6. Update publication, freshness, Pages and browser acceptance documentation.
7. Preserve historical v1 packages as immutable archives when required for
   provenance; do not keep two active production readers.

Acceptance:

- the three formal baselines retain their accepted identity, cutoff, research
  boundary and evidence limitations;
- deterministic promotion, freshness, static build, desktop/mobile browser and
  public-origin tests pass;
- no v1-only runtime path remains;
- rollback evidence and migration receipts are retained.

Must not include:

- new model selection;
- changed metrics caused by refitting;
- deletion of immutable provenance.

Dependencies: PRs 2–6.

## 6. Cross-PR rules

Every implementation PR must:

1. remain `research_only=true` and `trade_ready=false`;
2. preserve candidate/reference instrument separation;
3. avoid post-result parameter, universe, cost or metric-definition tuning;
4. preserve missing evidence and failures explicitly;
5. include contract fixtures and tests with the implementation;
6. be safe to review independently and avoid unrelated strategy changes;
7. keep preview work non-blocking for unrelated frontend and research branches;
8. update this handoff when a dependency or boundary changes materially.

## 7. Ownership and parallel work

The sequence is dependency-ordered, not an exclusive work lock.

- PR 1 frontend trust repairs may proceed while PR 2 contract design is under
  review, provided both agree on the existing normalized projection.
- Model and provider experiments may continue and publish isolated artifacts;
  they do not need to pause for Bundle v2.
- Frontend visual improvements may continue when they do not create a new data
  authority or conflict with the navigation migration in PR 4.
- Shared schema, loader and catalog changes require coordination through the
  tests and ownership declared by the active PR.

## 8. Program completion criteria

The program is complete when:

- a new governed model iteration can be exported and opened without a frontend
  source-code change;
- local, preview and formal publication statuses are unambiguous;
- the frontend never derives a stronger claim than the retained package;
- all comparable metrics use canonical IDs and availability semantics;
- incompatible evidence cannot be ranked as if it were like-for-like;
- a researcher can identify capability, risk, robustness, evidence gaps,
  verdict and next validation from one run review;
- the three existing formal baselines are migrated without changing accepted
  research results;
- static Pages, offline reopening and public-origin verification remain intact.
