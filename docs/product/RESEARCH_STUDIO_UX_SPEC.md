# Alpha Engine Research Studio UX Specification

## Product posture

The frontend is a professional research evidence workspace, not an execution terminal, retail trading screen or backend administration console. It helps a researcher answer four questions:

1. What evidence bundle is open?
2. What conclusions does it contain?
3. Why do candidate results differ?
4. Can every claim be traced to a contract, cutoff and immutable artifact?

## Information architecture

### Library

- **Library** — open a published, folder, file-set or ZIP bundle; reconnect recent local sources.
- **Overview** — evidence scope, latest conclusions, warnings, blocked gates and next reading paths.

### Evidence

- **Backtests** — performance, drawdown, costs, holdings, signal and execution evidence.
- **Models** — model identity, declared contract, metrics and promotion decision.
- **Compare** — side-by-side candidate comparison.
- **Data, Factors, Experiments, Reports** — artifact-native evidence views delivered by the next visualization wave.

### Reference

- **Methodology** — fixed research contract and interpretation boundaries.
- **Documentation** — connected runtime implementation reference.

### Developer

Training, jobs, system health, agents, mutation controls and experimental operational tools appear only in connected mode. Internal tools require explicit operator mode.

## Visual language

- neutral research-paper surfaces with one blue evidence accent;
- compact labels and tabular numerics for provenance and metrics;
- no neon market colors, fake ticker urgency or decorative glass effects;
- borders and tonal separation replace heavy shadows;
- one primary hierarchy per screen;
- dense controls only where comparison needs density;
- persistent evidence cutoff, runtime and integrity context.

## Shell anatomy

1. **Research rail** — grouped navigation and current bundle context.
2. **Page title bar** — page identity, model selector where applicable and global theme/account controls.
3. **Evidence context bar** — bundle, cutoff, markets, runtime, research-only and integrity state.
4. **Reading canvas** — maximum 1640 px, responsive cards and tables.

## Responsive behavior

Desktop is optimized for analytical comparison. Tablet keeps the rail and reduces page gutters. Below 768 px, the rail is removed from document flow and the content becomes a single scrolling canvas. A dedicated mobile navigation sheet remains a later refinement; every critical destination stays reachable through direct routes and the overview reading paths.

## Interaction and accessibility

- keyboard-visible focus for every action and route;
- active navigation uses text, background and a structural left marker rather than color alone;
- reduced-motion media query suppresses nonessential transitions;
- status context is exposed with `role=status`;
- chart views must include table summaries in the visualization wave;
- destructive controls never appear in static or local modes.

## Critical journeys

1. First visit → inspect published example → understand research-only boundary.
2. Open local bundle → validate core indexes → switch automatically to its models.
3. Library → reconnect folder after permission expiry.
4. Overview → model/backtest → compare candidates → methodology.
5. Connected runtime → deliberately enable developer tools → run operational workflows.

## Acceptance boundary

This design wave establishes the shell, hierarchy, navigation, Library and persistent context. It does not claim screenshot-based visual QA because no browser capture environment is part of this implementation run. Quantitative evidence modules and browser-level acceptance are delivered in #304 and #305.
