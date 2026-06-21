# End-to-End User Flow Map

## Step 1: Data Page (Update & Status)
- **Route:** `/#/data`
- **API:** 
  - `GET /api/data/status`
  - `POST /api/data/update`
- **Success Signal:** `quality_status='ok'`, `snapshot_id` exists. UI shows "Pass" and symbol accounting.
- **Failure Signal:** Network error, no snapshot available, or `symbols_failed > 0`. UI shows error banner or missing data state.
- **Frontend State:** Handled by `api-client.ts` fetchers.
- **Bug IDs:** BUG-002, BUG-003
- **Test:** `e2e/fixture-gaps.spec.ts` (Empty state and tracking)

## Step 2: Training & Backtest Job Execution
- **Route:** `/#/data` (Triggered via "Train on this snapshot" dialog)
- **API:**
  - `POST /api/workflow/train`
  - `GET /api/workflow/status`
- **Success Signal:** Job completes with `status='SUCCESS'`, yielding `run_id` and `workflow_id`.
- **Failure Signal:** `status='FAILURE'`, error details visible in job logs.
- **Frontend State:** Progress tracking polling `/api/workflow/status`.
- **Bug IDs:** BUG-004
- **Test:** `e2e/live-backend-audit.spec.ts` (Real execution)

## Step 3: Model Registry & Evaluation
- **Route:** `/#/models`
- **API:** 
  - `GET /api/models`
  - `POST /api/models/promote`
  - `POST /models/delete`
- **Success Signal:** Models list loads, stage is shown (e.g., STAGING), promotion succeeds.
- **Failure Signal:** API 404/500, missing metrics, or model not found.
- **Frontend State:** Model list cached and updated on mutation.
- **Bug IDs:** BUG-005
- **Test:** `e2e/fixture-gaps.spec.ts` (Promotion/Delete checks)

## Step 4: Comparison & Evidence Gathering
- **Route:** `/#/models` (Triggered via "Compare" actions)
- **API:** 
  - `GET /api/evidence/model/{id}`
- **Success Signal:** Model comparison page loads, showing `evidence_id` and completeness score.
- **Failure Signal:** Missing evidence ID, missing snapshot reference.
- **Frontend State:** Extracted from model object payload.
- **Bug IDs:** BUG-007
- **Test:** `e2e/fixture-gaps.spec.ts` (Identity persistence on reload)

## Step 5: Dashboard & Reporting
- **Route:** `/#/reports` or embedded in Models/Dashboard
- **API:** 
  - `GET /api/reports/`
  - `GET /api/reports/{report_id}`
  - `GET /api/reports/export`
- **Success Signal:** High-level metrics load (Sharpe, MDD). Report download button fetches the artifact successfully.
- **Failure Signal:** Missing data points, download returns 404.
- **Frontend State:** Chart states, blob download handler.
- **Bug IDs:** BUG-006
- **Test:** `e2e/fixture-gaps.spec.ts` (Report download event)
