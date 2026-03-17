# AlphaEngine Refactoring & Architecture Evolution

## 1. Product Vision & Positioning
**AlphaEngine** is a **local-first quantitative research workbench**. 
- **Core Goal**: Provide an integrated environment for data acquisition, feature engineering, strategy backtesting, and production-ready inference.
- **Agent Integration**: Leverages an "Advisory Agent" pattern (Alpha, Risk, Governance) to assist the human researcher, rather than replacing them with a black-box autonomous system.
- **Backend Philosophy**: Agent-friendly, metadata-driven, and highly reliable.

## 2. System Boundaries
- **Research Runtime (Domain)**: Qlib integration, feature resolution, backtesting engines.
- **Application Layer**: Daily routines, task orchestration, and specific use cases (e.g., Weekly Quant Rating).
- **Interfaces**: API (FastAPI), CLI, and future MCP/WebUI.
- **Advisory Layer (advisors_agent/)**: Specialized agents providing insights on Alpha, Risk, and Governance.

## 3. Directory Structure Strategy
```text
/mnt/GitHub/alpha_engine/
├── src/
│   ├── common/           # Shared utilities, config, paths
│   ├── data/             # Data adapters and validation
│   ├── research/         # Domain-specific research logic (to be consolidated)
│   ├── governance/       # SQLite-backed governance & audit storage
│   ├── reliability/      # Typed event system and failure classifiers
│   ├── workflows/        # Orchestration hooks and routine definitions
│   ├── api/              # FastAPI routers and dependencies
│   └── advisors_agent/   # AlphaAgent, RiskAgent, GovernanceAgent
├── configs/              # Metadata-driven feature/model resolution
└── artifacts/            # Local SQLite DBs, logs, and research outputs
```

## 4. Migration Plan (Phased)
1. **Infrastructure (Current)**:
   - [x] Governance SQLite storage foundation.
   - [x] Reliability typed event system.
2. **State & Task Management**:
   - [ ] Daily routine task/state driver (SQL-backed).
   - [ ] Migration from README-based logging to structured SQL auditing.
3. **Data & Features**:
   - [ ] Metadata-driven feature resolution (Inference config).
4. **Orchestration**:
   - [ ] Refactor `orchestrator.py` into importable hooks.

## 5. Execution Rules
- Maintain backward compatibility where possible.
- Favor SQLite over plain text files for state.
- Keep the system runnable outside the `agents/` ecosystem (independent workbench).
