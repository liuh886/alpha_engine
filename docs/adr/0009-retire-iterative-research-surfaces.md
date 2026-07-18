# ADR-0009: Retire Iterative Research Surfaces

**Date:** 2026-07-18
**Status:** Accepted
**Supersedes:** ADR-0006's implied loop semantics in `run_iterative_research`

## Context

ADR-0006 made `SpecBoundResearchWorkflowExecutor` the default `ResearchWorkflow`
runtime. The market-to-spec mapping is fixed: `cn` → `cn_10d_csi300_baseline.yaml`,
`us` → `us_10d_qqq_baseline.yaml`. The free-text `goal` is audit metadata only —
it does not change what the fixed spec executes.

Two surfaces exposed "iterative research" as a valid loop:

1. **`mcp_server.py` `run_iterative_research`** — an MCP tool that called
   `create_research_workflow().run()` in a for-loop (default 5 iterations). Each
   iteration executed the same fixed spec with the same fixed parameters. The
   `goal`, `target_sharpe`, and `max_iterations` were audit metadata only and
   could not vary the execution.

2. **`src/agents/research_loop.py`** — a module with `run_iterative_research()`,
   `run_iterative_research_from_goal()`, `run_research_loop()`, and
   `decide_next_action()`. These functions used the legacy scan→compile→
   backtest→attribute→promote pipeline (not the canonical spec-bound path) and
   implied scientific iteration via parameter variation that does not exist.

Repeating an unchanged fixed CN/US spec is not scientific iteration. A loop that
re-runs the same spec 5 times with the same parameters can overwrite
experiment-scoped evidence (run directory collisions) and misrepresents itself as
an adaptive research process when it is a fixed execution repeated.

## Decision

**Iterative research surfaces are retired or deprecated.**

1. **`mcp_server.py` `run_iterative_research`** is **removed**. No MCP tool
   exposes a loop over the same fixed spec. Callers use `run_research_cycle`
   for a single canonical execution.

2. **`src/agents/research_loop.py`** is **deleted in its entirety**. Every
   function, dataclass, and helper — `run_research_cycle` (legacy scan
   path), `run_iterative_research`, `run_iterative_research_from_goal`,
   `run_research_loop`, `decide_next_action`, `CycleResult`, and
   `IterationDecision` — is gone.  The legacy scan→compile→backtest→
   attribute→promote pipeline was superseded by the canonical spec-bound
   `create_research_workflow().run()` path and had no remaining production
   callers after `weekly_research.py` was migrated.

3. **`scripts/weekly_research.py`** uses the canonical
   `ResearchWorkflowResult` directly — no `CycleResult` adapter.
   `_run_research_for_market` calls `create_research_workflow().run()` and
   returns `ResearchWorkflowResult | None`. The `--max-iterations` CLI
   parameter is removed.

4. **`scripts/generate_weekly_report.py`** accepts canonical
   `ResearchWorkflowResult` objects and truthfully reports workflow status,
   promotion status, `trade_ready`, and run identity.  It does not invent
   per-factor scan counts, Sharpe ratios, or backtest performance metrics
   that the spec-bound path does not produce.

## Why the MCP `run_research_cycle` tool remains

`run_research_cycle` (MCP tool) executes a single canonical spec-bound workflow
via `create_research_workflow().run()`. It does not loop, vary parameters, or
imply scientific iteration. It is the single authoritative MCP surface for
triggering research execution.

## Consequences

1. No MCP tool exposes iterative re-execution of an unchanged fixed spec.
2. `src/agents/research_loop.py` is deleted (~1,000 lines).  The weekly
   adapter and report generator use `ResearchWorkflowResult` directly.
3. `scripts/weekly_research.py` uses the canonical path (one invocation per
   market per week).  Weekly reports reflect canonical workflow status,
   promotion status, `trade_ready`, and run identity — truthful, not
   fabricated from unavailable metrics.
4. The `--max-iterations` CLI parameter is removed from
   `scripts/weekly_research.py` — there is no iterative loop to cap.
5. The canonical CN/US spec-bound execution, evidence gates, and
   ResearchAssistant architecture are unchanged.
6. ``scripts/weekly_research.py`` CLI flags ``--market``, ``--skip-data``,
   and ``--skip-decay`` are wired to ``run_weekly_research()`` parameters
   and function as described in the CLI help text (ADR-0009 transitional
   placeholder removed).  ``setup_cron.py`` passes ``--market us``, so
   cron/PM2 runs only the US market as intended.
