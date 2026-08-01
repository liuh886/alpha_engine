# Alpha Engine: Agent Architecture

## 0. Current Active Program

Alpha Engine is research-only. The current active program is to complete the
model-ready data plane for the user-approved selected universes:

- US candidate pool: `configs/research_universes/us_selected_equities_v2.yaml`
  with 87 equities;
- CN candidate pool: `configs/research_universes/cn_selected_equities_v3.yaml`
  with 130 equities;
- selected-pool governance:
  `configs/pools/selected_pool_registry_v1.yaml`;
- reference instruments:
  `configs/pools/reference_instrument_registry_v1.yaml`.

The next model cycle may train and evaluate specifically on these fixed selected
pools. Full historical index-membership reconstruction is not a prerequisite for
this contract. Listing, delisting, suspension, tradability, data availability and
execution-time boundaries remain mandatory.

Approved ETFs and indices may provide benchmark, regime, risk-budget, relative
factor or explicitly authorized portfolio context. They remain separate from the
candidate cross-section. An index and an ETF tracking that index are distinct
instruments, and an executable ETF requires explicit strategy authorization.

The active data workstreams are:

1. reusable point-in-time fundamental coverage for US 87 and CN 130;
2. reusable corporate-action, adjustment and lifecycle coverage;
3. a governed proprietary and public formula-factor library;
4. machine-readable readiness gates before model training.

The former 23-name US daily-bar fundamental path remains a valid
strategy-specific narrow contract. It is no longer the only permissible research
path and must not silently replace the selected US 87 model pool.

Complexity and truth controls:

1. Build reusable provider adapters, event stores and incremental scripts rather
   than company-specific spreadsheets or one-off parsers.
2. Do not silently drop a selected candidate, substitute another security,
   forward-fill unavailable statements, or mix raw and adjusted prices.
3. Keep candidate and reference instruments role-separated and market-isolated.
4. Bind pool, reference, provider, fundamental, corporate-action and factor
   identities into every authoritative run manifest.
5. Imported public factors begin as unvalidated formulas; they are not bulk
   promoted or assumed effective.
6. Preserve failed factors and data blockers as cumulative research memory.
7. Do not tune model parameters, factor definitions, costs or pool membership
   after observing the same evaluation evidence.

Older OHLCV rankers, state machines, factor scanners and dashboard workflows are
retained as historical or diagnostic capabilities. They are not automatically
reactivated by the data-plane program.

## 1. Agent Runtime

The agent system uses a single unified **ResearchAssistant**. An **AgentRouter**
provides a thin dispatch facade, and **BaseAgent** provides shared utilities.

| Component | Role | Location |
| :--- | :--- | :--- |
| **ResearchAssistant** | Unified research, risk, governance, and architecture assistant | `src/agents/research_assistant.py` |
| **AgentRouter** | Thin task-dispatch facade | `src/agents/agent_router.py` |
| **BaseAgent** | Shared agent utilities | `src/agents/core/base_agent.py` |

The former Alpha, Risk, Governance, and Developer agents are conceptual roles,
not separate runtime agents.

## 2. Operating Protocol

For the current program:

1. **Identity resolution**: load the exact selected pool and reference registry,
   verify hashes, aliases, lifecycle boundaries and market isolation.
2. **Source build**: refresh source-bound price, fundamental and
   corporate-action data through reusable incremental adapters.
3. **Coverage audit**: report every selected symbol, missing field, conflict,
   availability boundary and factor applicability status.
4. **Factor build**: compute only versioned catalog factors whose required fields
   and lags are satisfied.
5. **Training gate**: open a model experiment only when its declared coverage,
   label, benchmark, cost and evidence contracts pass.
6. **Evidence run**: execute the frozen model and portfolio contract without
   post-result membership, factor or parameter substitution.
7. **Decision**: write a manifest-bound supported/not-supported result and retain
   the full failure record.

All outputs remain `research_only=true` and `trade_ready=false`. No agent may
send orders or describe diagnostic outputs as live trading recommendations.

## 3. Documentation Authority

- `AGENTS.md`: current operating route and complexity limits.
- `DESIGN.md`: long-lived design and historical decision record.
- `configs/pools/selected_pool_registry_v1.yaml`: default candidate-pool
  governance.
- `configs/pools/reference_instrument_registry_v1.yaml`: ETF/index identity and
  role governance.
- frozen YAML contracts: authoritative factor, source, pool, portfolio and
  evidence definitions.
- Issue #282: model-ready data-plane program.
- Issue #283: point-in-time fundamentals.
- Issue #284: corporate actions and adjustments.
- Issue #285: factor-library consolidation.
- Issue #286: selected-pool and reference governance.

Historical claims in older files do not override the current research-only
boundary or the active-program rules above.
