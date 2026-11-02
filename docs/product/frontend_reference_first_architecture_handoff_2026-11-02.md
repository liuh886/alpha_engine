# Alpha Engine — A-first 前端架构实现与 Agent 接手清单

**Owner decision:** 2026-11-02, A / Decision-first Investment Research Workspace.
**PR:** #1357, Draft / implementation foundation; **not yet CI- or browser-validated**.
**Scope:** page responsibility, route/nav, cross-page journeys, reuse of existing evidence readers; no new storage, computation, API, trading or permission change.

## 1. Implemented foundation on this PR branch

| Surface | Code | Responsibility |
| --- | --- | --- |
| Today | pages/StrategyOverviewPage.tsx | Default research brief, up to three source-verifiable priorities, links to all formal strategies and research |
| Strategies | pages/StrategiesPage.tsx | Reuse existing StrategyFleet and OperationsReadStatus, no new performance calculator |
| Research Lab | pages/ResearchHubPage.tsx | Racetrack local projection / RDI historical reviewed evidence, separate from operations |
| System | pages/SystemHubPage.tsx | Source status, operating reader and recovery; RDI deep link instead of research body |
| Workspace shell | routes.ts, App.tsx, Sidebar, MobileNavigation, MobileTabBar | Task-based destinations; Research/System not hidden by formal catalog load failure |
| Legacy reads | existing StrategyDetailPage, SecurityDetailPage, RacetrackWorkspace, RdiResearchStatus | Unchanged data authority, model evidence and permissions |

User journeys: **Today -> Strategy detail -> evidence/instrument**; **Today -> Strategies -> comparative history**; **Research -> Racetrack / RDI**; **System -> affected source / existing workflow**.

Existing /app?view=racetrack bookmarks remain accessible via the old query parameter and the unchanged RacetrackWorkspace. The new /research destination is an additional entry point and does not publish private runner evidence to GitHub Pages.

### Important limitations / intentionally unfinished

- Routing and TSX files were authored through GitHub API. Neither npm build, unit tests nor Playwright were executed in this session; no visual screenshot exists yet.
- In PR #1357 the route expansion (Today, Strategies, Research, System) is an **architectural review default** following A; Owner has not separately signed off final D2 navigation density. Do not deploy or claim final release from this Draft PR.
- The Today market cards currently show only formal strategy identity/count, not a new live US/CN market cutoff. Do **not** infer a common market date from different formal histories.
- StrategyDetail still needs task-oriented subsection navigation and Evidence-first ordering. InstrumentDetail still uses existing Recharts candles; Lightweight Charts 5.2.1 is already installed, but adapter POC is not in this PR.
- RDI stays not validated; only source-bound descriptive observations are available. Research Lab does not turn them into a forecast.

## 2. Agent backlog — execute in order, one purpose per follow-up PR

### H0 (P0): Stabilize PR #1357 before merge

- [ ] Check out branch and run qlib-dashboard npm ci, npm run lint, npx tsc --noEmit, focused Vitest route/navigation tests.
- [ ] Update all affected Playwright journeys. Known old assumptions occur in e2e/static-artifact.spec.ts, live-pages.spec.ts, strategy-operations.spec.ts: two nav items, Overview/Status labels, fleet on default /app, RDI inside /system. Preserve the **actual** research/data assertions while changing route destinations; never simply delete meaningful tests.
- [ ] Verify old Racetrack URL and new /research?section=racetrack with valid localhost fixture; query param transitions and browser Back must preserve market/window/runner selection.
- [ ] Verify /research?section=rdi is reachable when formal strategy catalog fails, independently of /system source health; exercise evidence mismatch states.
- [ ] Verify navigation (1440/768/375 px), mobile bottom tabs, sidebar, focus restoration, hash deep links, overflow, keyboard and screenreader labels.
- [ ] Verify unauthenticated/public/pro/owner permission behaviour with authentic test sessions if available; otherwise NOT_TESTED. Public current signal must never leak via Today or Research.
- [ ] Attach screenshots, test commands/results and SHA to PR #1357. Only merge after regressions are resolved and Owner reviews changed information architecture.

### H1 (P0): Today information design

- [ ] Replace the placeholder market identity summary with existing verified source-cutoff facts only when a separate trusted market-status reader is available; distinguish provider, formal run and target date.
- [ ] Improve four-strategy cards with current changed/retained/attention status using the **existing** access-aware observation renderer; do not duplicate computation or expose protected data.
- [ ] Keep high-priority feed max 3 and full fleet complete. Clarify what needs review next and provide one evidence CTA per item.
- [ ] Acceptance: user sees a real item, reaches its evidence/limitations in <=2 clicks and returns without losing context.

### H2 (P0): TradingView on instrument detail

- [ ] Use installed lightweight-charts 5.2.1 in SecurityHistoryChart POC; validated SecurityBar -> OHLCV and SecurityEvent -> grouped historical model-event markers.
- [ ] Side-by-side with existing Recharts; assert same timestamp/OHLCV/event ID and no missing interval or invented non-trading-day bars.
- [ ] Keyboard-accessible fallback in retained ledger, responsive mobile/desktop crosshair, zoom, date controls, attribution/NOTICE.
- [ ] Acceptance: improve financial-chart interaction while preserving source evidence and market adjustment semantics. Do not replace Strategy NAV until separately justified.

### H3 (P1): Strategy and Research detail

- [ ] Reorganize StrategyDetail into Summary / Performance / Risk / Decisions / Evidence (task-oriented tabs or anchors). One selected period must drive all comparable metrics, dates, benchmarks and risk panels.
- [ ] Reshape RDI primary reading as question -> supported historical descriptive result -> what remains unvalidated -> expandable source certification. Do not introduce a live composite score.
- [ ] Refine Racetrack hosted/local states; prohibit private Q publication; maintain independent formal/Runner/benchmark identities.

### H4 (P1): System usability and design prototype

- [ ] System should show affected source/strategy, last-good cutoff when available, failure class and existing workflow link; no duplicate full Daily Brief.
- [ ] Capture actual current screenshots and create three variants of **A-only** layout refinements (not reopen Owner-selected A vs B vs C). Show desktop 1440, tablet 768, phone 375, light/dark, normal/loading/restricted/stale.
- [ ] In ChatGPT Work mode use Product Design for a live URL capture and clickable prototype; ordinary chat does not have that full Product Design workflow.

### H5 (P2): Authority and release

- [ ] Resolve D2–D6 decisions with Owner, then update strategy_console.md / AGENTS.md / next_stage_execution_plan.md based on the *merged actual code*, not planned routes.
- [ ] Run full frontend CI/Playwright before actual Pages switch, verify deployment SHA, test rollback and preserve A0–A7 Owner release conditions.
- [ ] Merge of #1357 alone is **not** product A7 GO, runtime authentication certification, or permission for new research data publication.

## 3. Completion template for every Agent PR

User task before/after; reused components and external LICENSE; precise source/identity/cutoff/access invariants; focused test commands + result; browser screenshot paths and viewport; known FAIL/BLOCKED/NOT_TESTED; rollback and which PR/commit owns the change.

## 4. Product acceptance checks

- Today answers What changed / Why / Evidence / Next without exposing unsupported current targets.
- Strategies keeps all formal identities, exact strategy benchmarks and honest evidence windows.
- Research clearly labels local-only, unvalidated, and independently published experiments; System remains operational.
- Browser refresh never triggers a trade, research run or data-provider refresh.
- User-facing UI looks and behaves like an investment research workspace, not an admin dashboard or counterfeit trading terminal.