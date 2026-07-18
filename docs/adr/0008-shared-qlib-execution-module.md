# ADR-0008: Shared Qlib Execution Module with Two-Adapter Seam

**Date:** 2026-07-18
**Status:** Accepted
**Module:** `src.research.qlib_execution_common`
**Interface:** `ExecutionRuntime` Protocol, `execute_qlib_plan()`

## Context

The CN and US fixed-10D Qlib execution adapters (`cn_qlib_execution_adapter.py`
and `us_qlib_execution_adapter.py`) were ~600 lines each with only ~50 lines
of real differences. Both adapters performed identical readiness checks,
coverage alignment, window sampling, 10-session purge, per-window ranker
fitting, baseline loading, raw 10D evaluation, report/stability aggregation,
skip-result handling, and evidence writing. The only true differences were:

- Provider market tag (`"cn"` vs `"us"`)
- `QlibCNExecutionRuntime` vs `QlibUSExecutionRuntime` (concrete Qlib
  initialisation, `list_instruments` behaviour)
- `model_type` discriminator (`"spec_bound_cn_daily_ranker"` vs
  `"spec_bound_us_daily_ranker"`)
- Market-specific string literals in error messages and NaN-validation
  contexts

The `qlib_execution_common.py` module already owned market-neutral helpers
(`materialize_ranker_candidates`, `build_effective_execution_contract`,
`fit_ranker_scores`, `build_skip_result`), but the full execution pipeline
was duplicated across the two adapters.

## Decision

**A single shared execution engine owns the full plan execution
Implementation.** Specifically:

1. `src/research/qlib_execution_common.py` defines:
   - **`ExecutionRuntime` Protocol** — the single shared market-data surface
     (replaces the identically-shaped `CNExecutionRuntime` and
     `USExecutionRuntime` Protocols).
   - **`execute_qlib_plan()`** — the full execution engine accepting a
     `market` discriminator (`"cn"` or `"us"`). Every market-specific string
     is derived from this single parameter:
     - `model_type` → `f"spec_bound_{market}_daily_ranker"`
     - Calendar-empty reason → `f"{market.upper()} Qlib calendar is empty…"`
     - NaN-validation context → `f"{market.upper()} spec-bound train/…"`
     - All `market=` kwargs in readiness specs, universe reports,
       `SpecBoundEvaluationContext`, and `normalize_market_symbols` calls.

2. `cn_qlib_execution_adapter.py` is a **thin market Adapter** (~115 lines)
   containing:
   - `CNExecutionRuntime = ExecutionRuntime` (public-name re-export)
   - `QlibCNExecutionRuntime` concrete class (provider init with
     `market="cn"`, `list_instruments` with `level="market"`)
   - `execute_cn_qlib_plan()` — a one-line delegation to
     `execute_qlib_plan(…, market="cn", …)` with default-runtime fallback

3. `us_qlib_execution_adapter.py` is a **thin market Adapter** (~125 lines)
   containing:
   - `USExecutionRuntime = ExecutionRuntime` (public-name re-export)
   - `QlibUSExecutionRuntime` concrete class (provider init with
     `market="us"`, `list_instruments` with `freq="day", as_list=True`)
   - `execute_us_qlib_plan()` — a one-line delegation to
     `execute_qlib_plan(…, market="us", …)` with default-runtime fallback

## Why a single `ExecutionRuntime` Protocol with aliases

The two Protocols were structurally identical (same six method signatures).
Rather than maintain a common base plus two empty sub-Protocols, we define
one `ExecutionRuntime` Protocol in the shared module and re-export it under
the market-specific names (`CNExecutionRuntime`, `USExecutionRuntime`) in
each thin adapter. This preserves every public type name while having one
source of truth. Python's structural Protocol subtyping means any object
satisfying `ExecutionRuntime` automatically satisfies `CNExecutionRuntime`
and `USExecutionRuntime`.

## Consequences

1. The execution pipeline (~430 lines) lives exactly once in
   `qlib_execution_common.py`. A change to readiness, alignment, window
   sampling, ranker fitting, or evidence writing is made in one place and
   immediately applies to both markets.
2. The thin adapters (~115–125 lines each) contain only market-specific
   provider initialisation and symbol discovery. They are easy to audit for
   correctness — nothing in `execute_cn_qlib_plan` or `execute_us_qlib_plan`
   can diverge because both are one-line delegations.
3. No public name changes. All imports of `CNExecutionRuntime`,
   `USExecutionRuntime`, `QlibCNExecutionRuntime`, `QlibUSExecutionRuntime`,
   `execute_cn_qlib_plan`, and `execute_us_qlib_plan` continue to resolve.
4. The `ExecutionRuntime` Protocol is the single extension point for future
   markets — add a new thin adapter with its concrete runtime class and a
   `market` string, and the shared engine handles everything else.
5. Boundary tests now verify that thin adapters delegate (not re-implement)
   and that the shared engine owns `SpecBoundEvaluationContext` and evidence
   paths. This prevents accidental duplication from creeping back.
6. ADR-0002 ("Adapters Must Not Own Research Semantics") is strengthened:
   the thin adapters own no execution logic at all.

## Alternatives Considered

**Keep the two Protocols separate.** Rejected — they were structurally
identical, and maintaining two copies invited accidental drift. A single
Protocol with aliases preserves the public API surface without duplication.

**Move the Qlib runtime classes into common as well.** Rejected — the
concrete runtimes differ in `initialize` (provider market tag, manifest
checks) and `available_symbols` (`list_instruments` arguments), which are
genuinely market-specific. Keeping them in the thin adapters makes the seam
clear: provider surface vs execution engine.

**Parameterise every market string individually instead of using a `market`
discriminator.** Rejected — all market-specific strings are trivially
derivable from the single `market` tag. Passing six separate parameters
would increase the wrapper boilerplate and invite inconsistency.
