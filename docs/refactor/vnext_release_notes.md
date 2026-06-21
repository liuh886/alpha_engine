# Alpha Engine vNext Release Notes

## Overview
The vNext release transforms Alpha Engine from a feature-rich collection of pages into a streamlined, professional quantitative research terminal. We have consolidated the user experience into four core workflows, strictly enforced data contracts, and established rigorous performance budgets.

## Phase 1 & 2: Core Flow Simplification
- **Streamlined Navigation**: Reduced 15+ scattered routes down to 4 distinct paths:
  1. **Daily Research**: Data freshness, model readiness, and actionable daily insights.
  2. **Model Lab**: Training, comparison, and promotion of models.
  3. **Backtest & Attribution**: Backtest execution, performance curves, and factor attribution.
  4. **System & Ops**: Job tracking, diagnostics, and data quality checks.
- **Operator Mode Isolation**: Migrated system-level "Panic" controls and raw data overrides into an isolated Operator Mode, preventing accidental disruptions by general users.

## Phase 3: Pydantic Contract Enforcement
- **Data Integrity**: Enforced strict `response_model` usage across all FastAPI router endpoints.
- **Error Handling**: Standardized error responses to use `{"detail": "reason", "error_code": "code"}` schemas, parsed correctly by the frontend.
- **Hook Refactoring**: Extracted and standardized `useModels`, `useJobs`, and `useDataStatus` hooks. Eliminated interval leaks (e.g., in `useJobs.startPolling`).

## Phase 4: Frontend UI Modernization
- **"Research Cockpit" Dashboard**: Redesigned the primary dashboard using a 3-tier grid layout:
  - **Top**: System Readiness, Data Freshness, Active Jobs
  - **Middle**: Best Model, Latest Backtest, Risk Snapshot
  - **Bottom**: Recommended Actions, Recent Experiments
- **Unified Empty States**: Introduced a reusable `<Placeholder>` component to ensure consistent `Loading`, `Empty`, and `Error` states across all lists and tables.
- **Visual Polish**: Adopted a darker, highly professional theme using `tabular-nums` for all metrics and removing unnecessary gradients.

## Phase 5: Performance & Regression Protection
- **Performance Budget Established**: Formalized the requirement for the final Single-File UI bundle to remain under `< 450KB` gzip. Current measurement: `~402KB gzip`.
- **Release Checklist**: Created a structured sign-off checklist (`release_checklist.md`) encompassing layout fidelity, data contract verifications, and performance guarantees.

## Breaking Changes
- Direct access to deprecated URLs (e.g., `/factors`, `/arena`) will now redirect or show a simplified internal view depending on role access.
- Non-Pydantic API payloads from third-party integrations will be rejected by the backend.
