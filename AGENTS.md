# Alpha Engine: Agent Architecture

## 0. Current Active Path

Alpha Engine is research-only. The only active strategy-research path is the
small US daily-bar fundamental candidate:

- frozen pool: `configs/pools/us_small_pool_v1.yaml`;
- signal: revenue-growth acceleration plus gross-margin YoY change;
- cadence: evaluate every 20 sessions, with a 40-session minimum holding intent;
- data: Yahoo daily bars and SEC Company Facts using filed dates;
- entry point: `scripts/run_latest_us_fundamental_validation.py`;
- routine run: `.github/workflows/weekly-us-fundamental-validation.yml`;
- evidence decision: supported for future independent validation, or not supported.

Complexity controls:

1. Work on one active research family at a time.
2. Do not tune weights, thresholds, holding periods, baskets, symbols, or costs after observing results.
3. Do not add tree models, nonlinear searches, intraday logic, broker routing, or new dashboard surfaces to the current path.
4. Keep source applicability explicit; do not create company-specific filing parsers merely to increase coverage.
5. If the simple candidate fails, record the result and stop the hypothesis. If it passes, the next challenge is one small equal-weight multifactor baseline; only then may one Ridge challenger be considered.

Older OHLCV rankers, state machines, factor scanners, and dashboard workflows are
retained as historical or diagnostic capabilities. They are not the current
research direction and must not be expanded without an explicit new decision.

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

For the active path:

1. **Source check**: verify price and SEC source identity, freshness, and applicability.
2. **Evidence run**: execute the frozen single-factor contract once without parameter search.
3. **Risk check**: evaluate return, drawdown, turnover, holding duration, and concentration gates.
4. **Decision**: write a manifest-bound supported/not-supported result.
5. **Next action**: stop failed hypotheses; advance only supported simple baselines.

All outputs remain `research_only=true` and `trade_ready=false`. No agent may
send orders or describe diagnostic outputs as live trading recommendations.

## 3. Documentation Authority

- `AGENTS.md`: current operating route and complexity limits.
- `DESIGN.md`: long-lived design and historical decision record.
- frozen YAML contracts: authoritative factor, source, pool, portfolio, and evidence definitions.
- Issue #225: current fundamental-candidate evidence thread.

Historical claims in older files do not override the current research-only
boundary or the active-path rules above.
