# First season v2: Phase A contract

Implements the first bounded slice of #1312: the real US87 equal-weight pool
index also races. The four formal strategies remain formal-only. No demo racers,
CN admission, new registry, evaluator, scheduler, provider refresh or public
research projection is introduced. `research_only=true`, `trade_ready=false`.

## Version and activation

`alpha racetrack publish --market us --with-pool-runner` explicitly selects
pipeline 2.0.0 / schema 2.0. The default command remains pipeline 1.1.0 / schema
1.0, including its frozen PointsRuleV1 and cumulative display semantics. Existing
immutable releases remain readable; paired schema/pipeline versions fail closed.
Phase A rejects CN activation and combining the built-in racer with an external
registry. Later strategy admissions require their own frozen identities/inputs.

## Racer and evidence

`us87_ew_pool_runner_v1` version 1.0.0 uses the exact same pool event derivation
and V/NAV engine as the internal benchmark. Initialize at the first replay
close, then rebalance at observed monthly boundaries. Every declared candidate
retains a fixed 1/N slot at rebalance; unavailable slots become cash, never
redistributed. Weights drift between rebalances; the existing missing-valuation
policy remains explicit. A partial first month is not a complete calendar month.

The pool runner is evaluated once; its SimulationResult is also the internal
benchmark. The written Q ledger is retained under the immutable release's local
`evidence/` directory, with byte hash/size, event count and chain-tip hash bound
into `local_evidence` and release identity. It is not a browser artifact: the
local HTTP reader rejects evidence/JSONL resources, and nothing is copied to
public/dist. Failed validation does not advance the current manifest pointer.
Role `internal_benchmark_racer` is carried in the v2 `first_season.roles` map
and runner detail. Macro QQQ remains reference-only. The shared NAV is not a
copied formal-strategy return.

## Scoring and windows

- New rule `monthly_net_return_percentage_points_v2`: points = 100 × monthly
  net return, including negative values. Monthly ties earn equal points.
  Cumulative points are an arithmetic sum, not compounded NAV total return.
  PointsRuleV1 is retained unchanged; v2 emits the new rule explicitly.
- Season rank uses current-month return-points. Equal numeric values receive
  competition ranks (1, 1, 3); runner ID determines display order within ties.
- Window rank uses precomputed 1/3/6/12-month net return. A window starts at the
  last official trading session on/before `as_of_session - M calendar months`.
  That prior close is the NAV anchor; end NAV / anchor NAV - 1 is calculated
  only by the backend. Without the anchor in the replay, return/rank are null
  and the runner is short-history, never ranked on partial history.
- `first_season.windows` publishes anchor/end sessions, all ranks and ordered
  Top 10 IDs. The NAV payload retains the union of window Top 10 and season
  Top 10 IDs once, not four copies. The frontend switches published identities
  and slices/rebases; it never ranks, compounds returns or awards points.
- Monthly return derivation and risk evidence reuse the existing scorer. Excess
  uses eligible 1Y returns, otherwise full replay, labelled independently of the
  chart window. Inception friction belongs to its actual event/session.

## Completion, qualification and settlement

`month_windows` compares observed sessions to the official full calendar month.
`complete_window` is a coverage fact. `settlement_status=not_reviewed` and
`season_state=provisional` remain explicit even when the dates are complete.
This slice does not create a settled-season snapshot or imply operator review.
A later settlement contract must bind reviewed source/rule/calendar identities
without rewriting earlier immutable evidence. No month is declared settled here.

Unresolved candidate price gaps after first observation are counted and exposed
as `source_gaps`; a first observation is not certified listing time. Such gaps
must not become silently dropped candidates or fresh/tradable prices. Reading
the view does not resolve these gaps, refresh a source or certify historical PIT.

## Acceptance and next slices

Phase A requires exact racer/benchmark NAV equality, owned/hash-valid retained
Q events, atomic failure/idempotency tests, legacy reader compatibility,
negative/tied points, short-history exclusion, real-source publication and local
browser proof of role/detail/window behavior. Frontend QA uses repository
Playwright because the Browser plugin is not available in this session.

Next, under separate contracts: calendar-aware reviewed settlement snapshots;
exact formal-derived variants and reconciliation/model/factor inputs; CN spec
alignment/admission. This document does not authorize leverage, ETF/reference
holdings, silent clipping or changes to active formal strategy identities.
