# Formal Evidence Standard

## Purpose

This is the acceptance contract for every newly promoted formal research model in Alpha Engine. US x1.2 is the reference implementation.

Formal acceptance means the model has one named, governed, hash-verifiable research baseline. It does **not** mean the model is trade ready. Every formal bundle remains `research_only=true` and `trade_ready=false` until a separate operational decision says otherwise.

## Required formal surface

A newly accepted formal Bundle v2 must publish all of these sections as `available`:

- `summary`
- `performance`
- `risk`
- `robustness`
- `portfolio`
- `trades`
- `attribution`
- `diagnostics`
- `lineage`

`decision` remains a companion artifact because embedding a decision that contains the `bundle_id` would create a circular identity.

A new formal model may not enter the formal catalog with a required decision-support section omitted and hidden behind frontend fallback behavior.

## Canonical metric contract

`summary.metrics` must declare exactly one record for every canonical metric id supported by Bundle v2:

- total return
- annualized return
- benchmark return
- excess return
- annualized volatility
- Sharpe ratio
- information ratio
- max drawdown
- turnover
- transaction cost
- IC
- Rank IC
- ICIR

Every metric must carry an explicit availability state. The frontend never converts every non-value state into a generic `Unavailable` label.

Allowed states are:

- `available` — a governed retained value exists;
- `not_applicable` — the metric or field is outside the model/evidence contract;
- `not_computed` — the governed builder intentionally did not compute it;
- `not_retained` — historical authoritative evidence did not retain it;
- `blocked_by_source` — the source contract prevents a trustworthy value.

A missing value must never be represented as zero, inferred in the browser, or supplied by a fallback estimator.

## Performance semantics

A new formal model must explicitly declare, in the backend evidence package:

- signal time;
- execution time;
- return measurement;
- price basis;
- holding-end offset in sessions;
- cost rate;
- turnover formula;
- net-return formula.

`not_declared` is not an accepted value for these fields in a newly promoted formal model. The browser renders the declared contract and does not infer timing, cost, or price semantics from the model name.

## Completeness semantics

For a newly promoted formal model:

- `evidence_completeness.status` must be `complete`;
- `evidence_completeness.missing` must be an empty list;
- fields that are structurally outside the governed contract belong in `not_applicable`, not `missing`.

For US x1.2, brokerage quantity and brokerage fill price are `not_applicable` because there is no governed portfolio-capital, lot-size, or brokerage-fill contract. Normalized notional on NAV=1 and governed adjusted-close evidence are retained instead. No brokerage values may be fabricated to make the UI look complete.

## Publication and supersession

A formal promotion replaces the active formal baseline for its model family. The superseded model may remain as immutable historical evidence, but it must not remain in the active formal catalog and must not be shown as a second current baseline.

If a same-version preview exists, the formal record is authoritative in product views. The preview may remain as immutable provenance, but it is not an active duplicate surface.

There is no compatibility alias, fallback model id, or browser-side promotion rule.

## Formal acceptance vs trade readiness

Formal research acceptance and trade readiness are separate decisions.

An explicit model-governance decision may promote a fully evidenced model to the formal research baseline while a prospective trading gate remains incomplete. In that case:

- the formal promotion basis must be recorded in lineage;
- the prospective gate must remain explicitly pending;
- the pending gate may constrain trade readiness only;
- the system must not claim that the prospective gate passed;
- `trade_ready` remains `false`.

US x1.2 follows this rule: the explicit 2026-08-12 promotion makes it the accepted formal research baseline; its untouched six-month prospective requirement remains pending for trade readiness.

## Frontend contract

The frontend has one responsibility: render the verified backend state faithfully.

It must not:

- recompute missing formal metrics;
- infer execution semantics;
- turn `not_applicable`, `not_computed`, and `not_retained` into the same generic error state;
- treat `0` or `false` as undeclared;
- show a preview duplicate when the same model version is formal.

`Unavailable` is reserved for an actual section/load failure where governed evidence cannot be loaded or verified.

## Enforcement

`src/artifacts/formal_evidence_standard.py` is the machine validator for this contract. New native formal promotion paths must pass it before entering the formal catalog.
