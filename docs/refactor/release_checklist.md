# Release Checklist

This document formalizes the release gates and checklist for transitioning Alpha Engine updates into production (vNext).

## 1. Pre-Release Validation

### Core Functionality
- [ ] **Routing & Navigation**: Verify all main routes (Daily Research, Model Lab, Backtest & Attribution, System & Ops) render correctly and load data.
- [ ] **Data Flow**: Ensure API endpoints map accurately to the Pydantic schemas defined in the backend (Phase 3 contract).
- [ ] **State Management**: Test global store updates (e.g., active jobs, quality status, data freshness).

### User Experience
- [ ] **Empty States**: Verify `Placeholder` components are visible and correctly styled for empty, error, and loading states across all core views.
- [ ] **Sidebar Constraints**: "Panic" operations must remain isolated (only visible in Operator Mode or System page).
- [ ] **Visual Regressions**: Check `tabular-nums` formatting on metrics, ensure consistent color tokens for Status and Action cards, and verify dark-mode compatibility.

### Performance & Security
- [ ] **Bundle Budget Gate**: Run `npm run check:bundle-budget` (in `qlib-dashboard/`). This builds the production bundle, extracts all JS assets (standalone `.js` files or inline `<script>` blocks from the single-file build), gzips each independently, and exits non-zero if the total JS gzip exceeds 450 KB. CSS, HTML markup, and other non-JS content are excluded from the budget.
- [ ] **Memory Leaks**: Confirm polling logic (e.g., `useJobs`) correctly cleans up intervals to prevent timer leakage.
- [ ] **Lint & Tests**: 
  - `uv run ruff check .` must pass.
  - `uv run pytest -q` must pass.
  - `cd qlib-dashboard && npm run lint` must report 0 errors/warnings.
  - `cd qlib-dashboard && npm test` must pass all frontend tests.
  - `cd qlib-dashboard && npm run check:bundle-budget` must exit 0.

## 2. Release Steps

1. **Code Complete**: Branch merged with successful CI results.
2. **Version Bump**: Update version string in `pyproject.toml` and frontend `package.json` if applicable.
3. **Changelog**: Append release notes detailing user-visible features, structural improvements, and bug fixes to the CHANGELOG/Release Notes.
4. **Deploy**: Build and publish the static single-file dashboard, and deploy the updated FastAPI backend.

## 3. Post-Release

- Monitor the System & Ops page for unexpected panics or backend anomalies.
- Observe Data Quality metrics for anomalies in daily pipeline ingestion.
