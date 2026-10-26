# Alpha Engine — Investment Research Infrastructure (product direction proposal)

**Status:** PROPOSAL FOR DISCUSSION (2026-10-26). This document does **not** supersede the accepted single-operator ADR-0003, the owner-selected Direction A v1 in draft PR #1276, `AGENTS.md`, the four-strategy `docs/product/strategy_console.md`, any frozen research/data contract, or the research-only / trade-not-ready boundary. It authorizes no implementation, deployment, trade, model promotion, new data purchase, or permission change.

## The problem to solve

The product owner's ultimate investment aims are better after-cost returns, fewer poor decisions, and controlled drawdowns. Those outcomes are **not** engineering acceptance criteria and no model or infrastructure project can promise them.

**Our platform problem is upstream:** a new investment idea (cross-sectional ranking, market-state/risk-density hypotheses, portfolio exposure, a future idea) requires a trustworthy historical information set and an experiment that is reproducible, comparable, and capable of *rejecting* a bad hypothesis. Too much researcher time can otherwise go into custom ETL, source reconciling, building a bespoke runner and deciphering old evidence rather than asking a new question.

**Product positioning:** **Alpha Engine = a personal, evidence-governed Investment Research Infrastructure**, with existing formal strategy observation as one application. “Build reusable data and experimentation capabilities once; investigate many hypotheses without repeating plumbing.”

We are **not** declaring a “winning model”, building a generic market-data SaaS, or converting the existing Strategy Console into an in-browser research IDE.

## Product architecture: four responsibilities, not four new services

1. **Source & identity foundation.** Canonical US/CN instrument identities, listing/delisting and symbol change, universe/reference separation, raw/adjusted price roles, provider identity, release timestamps and source rights. Continue existing provider adapters, company events, fundamentals, corporate-action stores and approved registries.
2. **Research-ready data products.** Versioned, catalogued, verifiable domain-specific datasets (prices, fundamentals, corporate actions, factor panels, market/sector references, event observations). Reuse `model_data_bundle_v1` for declared profile readiness. Avoid a second data lake, registry, provider router or source-of-truth DB. “Available in a stored file” is not necessarily “known by a historical researcher.”
3. **Reproducible research execution.** Existing `alpha data` and `alpha research`, frozen experiment specs, Qlib/evaluators, benchmark/calendar/cost/PIT gates, immutable receipts and negative results. A common *research question → data requirements → eligible snapshot → experiment → evidence* path should be expressible without a bespoke pipeline for each hypothesis. The interface is a candidate abstraction for review, not authorization to add a new runner.
4. **Consumers.** Existing local researcher CLI/notebooks, four-strategy read-only Strategy Console, and independent research-specific views such as the RDI readiness display. Consumers read verified evidence and are never alternate canonical stores. Any future interaction surface is explicitly separately approved.

## Reusable product contracts to converge (prefer adapters to new systems)

### A. Dataset / historical information-state contract

A research dataset request must explicitly declare **market + identity + candidate/reference role + universe or instrument set + start/end + decision cutoff + data role + required fields + allowed source/version**. Returned data/evidence must make the following inspectable (or mark unsupported and block dependent claims):

| Dimension | Required semantics |
| --- | --- |
| Identity | Exchange, symbol/entity lineage, eligible membership *at the specified historical cutoff*, listing/suspension/delisting, benchmark vs candidate vs ETF reference |
| Time | Event/observation timestamp, release/publication timestamp, first verifiable availability (`available_at`), provider retrieval (`retrieved_at`), correction/revision history, timezone and exchange calendar; distinguish historical proof from timestamps generated today |
| Price | Raw execution prices vs cutoff-anchored adjusted research prices, dividends/splits/rights, source reconciliation, currency/unit |
| Completeness | Expected vs observed instruments/events, gaps, conflicts, source lag, pending/partial/blocked/unknown. **Unknown event ≠ zero events** |
| Trust | Provider/rights and redistribution class, hashes/source manifests, frozen transformation identity, precise cutoff, explicit permission/publication boundary |
| Versioning | Historical as-of state and accepted revision/vintage; immutable source facts, rebuildable projections, retention/reference stability |

Source-family-specific fields remain in their existing contracts. Do **not** create a universal fact table that flattens away these semantics. A catalogue/index may *reference* current manifests; it must not become competing authority.

### B. Research experiment contract

A reusable experiment declares:
- economic research question and falsifiable prediction (or an explicit descriptive/no-prediction objective);
- universe, benchmark, PIT information cutoff, feature/label horizons and availability lags;
- time-split/embargo or purging, holdout untouched rules, transaction costs, liquidity/execution assumptions and calendar;
- baseline and comparison plan, predefined evaluation measures and failure conditions;
- exact input manifests, factor/model/evaluator hashes, outputs, negative findings and independent reproduction receipt.

Model training, factor discovery and risk studies remain different **consumers** of the same contracts. No evidence of investment profitability is inferred from passing contract validation.

### C. Data access and research UX

First prefer a documented **local discovery / inspect / slice / check** journey atop existing `alpha data` facilities. A researcher should be able to answer *What exists? At what historical cutoff could it have been known? What is incomplete? What can I reuse? Why is a requested study blocked?* without reading dozens of PRs. Prove an existing path is missing before proposing additional CLI commands or screens.

## Explicit architectural invariants

- Single operator; **`research_only=true`, `trade_ready=false`**. No order routing or investment-signal promotion in this design PR.
- The four accepted strategies and their decisions/cadences are unchanged; historical model evidence remains immutable.
- Current v1 acceptance (#1277/#1279/#1281/#1282) continues in parallel. In particular, publication/privacy exposure #1288 and draft #1291 are **P0**, not deferred until the long-term data program.
- One authority per datum or decision; source manifests and registered contracts stay canonical; projections, front-end assets and caches remain disposable.
- No new permanent GitHub Actions workflow beyond the 39-workflow ceiling, scheduler, second data DB, factor engine, experiment runtime, or primary navigation without a measured gap and retirement/replacement plan.
- Distinguish “provider adapter present”, “historical backfill present”, “first-known time certified”, “eligible for a specific study” and “predictive result validated”. Never collapse them into “ready”.
- Avoid silent resampling, cross-source splicing, date substitution, forward fill, missing event = zero, hindsight universe selection or public release of protected current signals.
- Changes to canonical contracts, source entitlements, strategy identities, policies or formal publication require a *separate* approved issue and scoped review.

## How to tell if the platform improved

Evaluate platform usefulness independently from alpha profitability:
1. **Reuse:** fraction of new research data requirements served by existing verified products; number of genuinely new ETL/reader implementations needed.
2. **Time-to-first-valid-experiment:** measured time from a frozen research question to a manifest-bound research run; compare against the old workflow for the same scope.
3. **PIT truth:** coverage and truthful blocking of unsupported historical availability; zero proven look-ahead leakage in tested slices.
4. **Reproducibility:** exact/tolerance-bound independent repeat on locked inputs; all blocked and failed outcomes retained.
5. **Maintenance:** no parallel authority, no redundant full dataset copies, no creeping workflow/CI/permission burden.
6. **Operational safety:** v1 real-session proof, publication privacy, static/runtime account boundary and rollback remain separate mandatory acceptance.

These are proposed measures; baselines must be *measured*, not guessed.

## Product decision points for this draft PR

**D1 — Scope:** Ratify “Investment Research Infrastructure” as the **long-term umbrella**, while Direction A v1 remains the **short-term delivery scope**. Do not silently rewrite `AGENTS.md` or `docs/product_vision.md` before owner review.

**D2 — Research-first interface:** Start with local CLI/library and machine-readable evidence, not a new browser Research Studio. The Console stays a downstream observer.

**D3 — Data priorities:** For the first architecture pass, inventory all existing data products before buying news/macroeconomic feeds or widening instrument universe. Require source-rights and PIT proof before onboarding new families.

**D4 — Pilot selection:** Demonstrate infrastructure reuse using (a) selected-pool cross-sectional research and (b) RDI/event-density readiness as **two different consumers**, without changing their models or reporting RDI alpha. Pilot acceptance may be **blocked** where sources are missing; this is a valid infrastructure result.

**D5 — Governance:** Treat this proposal as an umbrella planning PR. After ratification, create *small*, independently auditable Issues from the roadmap; do not bundle implementation into this branch.

**Discussion questions:** Which data families merit expansion beyond US87/CN130? What is the lowest-friction research-facing interface? Which datasets have legally usable historical vintages? Where should we measure reusable slicing before investing in new ingestion?

See [baseline audit](../architecture/investment_research_infrastructure_baseline_2026-10-26.md) and [delivery roadmap](investment_research_infrastructure_roadmap_2026-10-26.md).
