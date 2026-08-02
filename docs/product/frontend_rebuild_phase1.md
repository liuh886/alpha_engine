# Frontend Rebuild — Artifact-Only Product Cutover

Status: **Phase 1 implementation**  
Parent: #316  
Delivery issue: #318

## Product decision

Alpha Engine has one Web product: the **Research Artifact Studio**.

The studio is a static, installable PWA that opens either a published research bundle or a user-selected local bundle. It does not connect to FastAPI, authenticate users, run jobs, refresh data, train models, mutate registries or operate infrastructure.

The browser answers four questions:

1. What evidence is loaded?
2. What is its scope, cutoff and integrity status?
3. How do model and backtest candidates compare under the same contract?
4. Which report, experiment or source file supports a conclusion?

## Target user outcome

A researcher should be able to open an Alpha Engine result folder and reach a defensible interpretation without understanding the repository's server history or starting a localhost process.

## Product boundary

```text
Python data / model / backtest workflows
                 ↓
versioned alpha-engine-bundle.json
                 ↓
Research Artifact Studio
```

### Browser responsibilities

- open published, directory, file-set or ZIP bundles;
- validate manifest compatibility, paths, sizes and hashes;
- show data, model, experiment, factor and backtest evidence;
- compare declared candidates;
- open manifest-declared reports and notebooks;
- work offline after first load;
- keep local files on the user's device.

### Browser non-responsibilities

- authentication;
- API reads or writes;
- job submission or polling;
- data refresh;
- training or backtest execution;
- model deletion or promotion;
- agent, system or infrastructure operations;
- trade execution.

## Information architecture

### Workspace

- **Overview** — evidence status, current bundle and recommended review paths.
- **Library** — open, reconnect, switch and close bundles.

### Evidence

- **Backtests** — performance, benchmark, drawdown, costs, holdings and signal/execution evidence.
- **Models** — model identity, windows, metrics, gates and promotion state.
- **Compare** — like-for-like candidate comparison.
- **Data** — lineage, coverage, scope, freshness and file integrity.
- **Factors** — catalog and evidence boundaries without equating importance with validity.
- **Experiments** — hypotheses, stop rules and immutable result links.
- **Reports** — manifest-declared reports and notebooks.

### Reference

- **Methodology** — fixed research contract and interpretation boundaries.

There is no Developer navigation group in the Web product.

## Visual and interaction direction

The interface should feel like a research notebook and evidence terminal, not an admin dashboard or retail trading app.

- calm neutral surfaces with restrained accent use;
- one primary reading hierarchy per page;
- provenance and boundaries visible without dominating the content;
- dense tables only where comparison requires density;
- no fake live-market urgency, status lights or operational chrome;
- consistent desktop, tablet and mobile review experience;
- keyboard-accessible selectors, dialogs and navigation;
- explicit empty, incompatible, stale and integrity-failure states.

## Phase 1 route classification

| Previous route family | Decision |
| --- | --- |
| Overview, Library, artifact Data/Models/Factors/Experiments/Reports | Retain and refine |
| Backtest dashboard and candidate comparison | Retain as artifact evidence |
| Methodology | Retain as reference |
| Login and identity | Delete from product runtime |
| Jobs, system health and console | Delete from product runtime |
| Data refresh and runtime data manager | Delete from product runtime |
| Training/backtest workbench | Delete from product runtime |
| Model deletion and runtime registry | Delete from product runtime |
| Agent, tools, stock terminal and arena | Delete from product runtime |
| Connected-only documentation | Remove from route graph; replace with artifact methodology/docs |

Useful research interpretation found only in a retired page must first move into the bundle contract and an artifact-native page. Operational controls are not reimplemented elsewhere.

## Runtime model

Only two source modes remain:

- `static_artifact` — published GitHub Pages bundle;
- `local_artifact` — local directory, file set or ZIP bundle.

Both modes are permanently read-only, offline-capable and free of `/api/*` requests.

## Quality gates

Phase 1 is complete only when:

- production routes contain artifact views only;
- `connected_research` is absent from production frontend code;
- the application root has no auth provider or login guard;
- bootstrap performs no server health, identity, job or data-status requests;
- model selection exposes no deletion action;
- TypeScript, lint and unit tests pass;
- static build and PWA validation pass;
- desktop, tablet and mobile Playwright journeys pass;
- browser acceptance observes zero `/api/*` requests;
- offline shell reload remains green;
- `research_only=true` and `trade_ready=false` remain visible.
