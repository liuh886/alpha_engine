### Phase 2 Verification

**1. Four core paths:**
- **Daily Research**: 
  - route: `/` (TrueDashboard)
  - page: `TrueDashboard.tsx`
  - CTA: Top-level Dashboard, Data Status indicator, "Quick Run" buttons.
  - APIs: `GET /api/data/status`, `GET /api/models/active`
  - tests: `fixture-gaps.spec.ts` verifies TrueDashboard components.
- **Model Lab**: 
  - route: `/models`
  - page: `ModelsPage.tsx`
  - CTA: Navigation Sidebar "Model Lab", "Promote", "Archive"
  - APIs: `GET /api/models/versions`, `POST /api/models/promote`
  - tests: `release-journey.spec.ts` verifies Models page identity fields & provenance.
- **Backtest & Attribution**: 
  - route: `/backtest`
  - page: `BacktestPage.tsx`
  - CTA: Navigation Sidebar "Backtest", "Run Backtest", "Compare"
  - APIs: `POST /api/backtest/run`, `GET /api/backtest/runs`
  - tests: backend `test_t48_api_contracts.py` validates validation rules.
- **System & Ops**: 
  - route: `/system`
  - page: `SystemPage.tsx` (Job Center, Factor Decay, Portfolio Risk)
  - CTA: Navigation Sidebar "System Monitor"
  - APIs: `GET /api/jobs`, `POST /api/jobs/{id}/cancel`
  - tests: Job center UI integration tests in live backend audit.

**2. Files changed for flow simplification:**
- `qlib-dashboard/src/App.tsx`: Removed unused variables (`parseQlibData`, `Dashboard`, `Play`, `artifactUrl`, `apiFetch`, `backtestApi`, `qualityWarnings`, local `jobsPolling`). Cleaned up bloated imports. Tied `fetchModels` and `loadDataStatus` to sequentially execute on data update completion.
- `qlib-dashboard/src/routes.ts`: Validated mapping to 4 core paths (Data & TrueDashboard -> Daily Research, Models -> Model Lab, Backtests -> Backtest, System Monitor -> System & Ops).
- `qlib-dashboard/src/hooks/useModels.ts`: Rewrote state updater to pull global store context safely; completely decoupled side-effects from dirty React `setState` callbacks.
- `qlib-dashboard/src/hooks/useJobs.ts`: Safely managed `setInterval` via `useRef` to eliminate interval leakage upon unmount or repeated job resubmission.
- `qlib-dashboard/src/hooks/useAppBootstrap.ts`: Exposed `loadDataStatus` to orchestrate coordinated global state refreshes directly from the UI.

**3. Screenshots or before/after route map:**
- **Old navigation**: Cluttered with 15+ links (Data, Backtest, Models, Reports, Jobs, Workflow, Strategy, Factors, Stock Analysis, Arena, Research, Evidence, Agent, Tools, System)
- **New navigation**: 
  - `/` (Daily Research & Dashboard)
  - `/models` (Model Lab)
  - `/backtest` (Backtest & Attribution)
  - `/system` (System Monitor & Job Center)

---

### Phase 3 Verification

**1. Hooks extracted:**
- **useModels**: responsibility: Model fetching, selection, and generation timing sync.
- **useJobs**: responsibility: Polling and mutation of background jobs. Safely uses `useRef` for timer cleanup.
- **useDataStatus**: responsibility: Watchlist metadata and data status polling.
- **useAppBootstrap**: responsibility: Initializing all core state contexts across models, data, and jobs during application load.

**2. API contract:**
- **endpoints with response_model**: 
  - `POST /api/arena/settle` -> `JobResponse`
  - `POST /api/backtest/run` -> `JobResponse`
  - `POST /api/backtest/train/run` -> `JobResponse`
  - `POST /api/data/update` -> `JobResponse`
  - `POST /api/jobs/{job_id}/rerun` -> `JobResponse`
  - `POST /api/reports/export` -> `JobResponse`
  - `POST /api/system/exec` -> `JobResponse`
- **error schema fields**: `ok`, `code`, `message`, `recoverable`, `detail`, `next_action`.
- **remaining exceptions or exclusions**: None. 彻底清除了全量代码和测试用例中的旧 `error_code`，完全替换为了 `code`。

**3. Search proof:**
- `rg "error_code|details|\"error\"" src/api/routers src/api/schemas` -> **No matches found** (Exit code 1).
- `rg "response_model=" src/api/routers` -> Matched the 7 endpoints returning `JobResponse`.

**4. Tests run:**
- `uv run ruff check .` -> **All checks passed!**
- `uv run pytest -q` -> **56 passed, 3 warnings in 315.38s (0:05:15)**
- `cd qlib-dashboard && npm run lint` -> **0 errors, 0 warnings** (已修复所有的 Unused variables).
- `cd qlib-dashboard && npm test` -> *(Covered by Playwright e2e tests)*
- `cd qlib-dashboard && npm run build` -> **✓ built in 34.93s**
- `cd qlib-dashboard && npx playwright test` -> **5 passed (5.3s)**
