# Bug Ledger

This ledger records identified bugs and execution paths during the Phase 1 stability audit.

## Confirmed Bugs
*(None identified in the core smoke path yet. Awaiting live-backend or deeper edge-case validation.)*

## Verified Working Paths (Fixture)

| Bug ID | Entry | Steps | Expected | Actual | Severity | Module | Status | Regression Test | Evidence / Screenshot | Owner |
|---|---|---|---|---|---|---|---|---|---|---|
| BUG-001 | Start -> Dashboard | Load app | Dashboard renders nav | Dashboard renders nav and symbols correctly against fixture | P0 | Frontend | Working (Fixture) | [e2e/release-journey.spec.ts](../../qlib-dashboard/e2e/release-journey.spec.ts) | - | TBD |
| BUG-002 | Empty Data State | Visit /#/data when API returns no snapshots | Bootstrap UI is shown to prompt data pull | UI shows "Update Data" button when snapshot data is empty | P0 | Frontend | Verified | [e2e/fixture-gaps.spec.ts](../../qlib-dashboard/e2e/fixture-gaps.spec.ts) | - | TBD |
| BUG-005 | Model Registry | Open Models page | Models list with promote/delete actions | Models list loads and promotion logic triggers correctly against fixture | P1 | Registry | Working (Fixture) | [e2e/release-journey.spec.ts](../../qlib-dashboard/e2e/release-journey.spec.ts) | - | TBD |
| BUG-006 | Network Errors | API returns 500/401/404 | Graceful error boundary or toast, not blank screen | UI successfully renders error banner when 500 is thrown | P1 | Frontend | Verified | [e2e/fixture-gaps.spec.ts](../../qlib-dashboard/e2e/fixture-gaps.spec.ts) | - | TBD |
| BUG-007 | Persistence | Reload page | Jobs and state recover from DB/URL | Success states persist natively across page reload | P1 | Frontend | Verified | [e2e/fixture-gaps.spec.ts](../../qlib-dashboard/e2e/fixture-gaps.spec.ts) | - | TBD |

## Pending Live Audit Risks

*(Note: These items cannot be validated fully via static fixtures. They are tracked via the `live-backend-audit.spec.ts` test suite. **This suite is skipped by default and is explicitly NOT a CI gate.** It serves purely as an executable checklist for developers verifying a live seeded environment.)*

| Bug ID | Entry | Steps | Expected | Actual | Severity | Module | Status | Regression Test | Evidence / Screenshot | Owner |
|---|---|---|---|---|---|---|---|---|---|---|
| BUG-003 | Data Update Tracking | Click update button | Progress tracking with success/fail verdict | Not verified. Requires seeded live backend to observe long-polling or failure states. | P1 | Job Center | Pending Live Audit | [live-backend-audit.spec.ts](../../qlib-dashboard/e2e/live-backend-audit.spec.ts) | - | TBD |
| BUG-004 | Train Failure | Train on invalid config | Error reason displayed explicitly | Not verified. Requires live backend to trigger stack traces and monitor UI. | P0 | Job Center | Pending Live Audit | [live-backend-audit.spec.ts](../../qlib-dashboard/e2e/live-backend-audit.spec.ts) | - | TBD |

## Severity Definitions
- **P0**: 启动失败、页面空白、API 认证失败、job 卡死、数据破坏
- **P1**: 流程可走但状态不一致
- **P2**: 展示错误、交互不顺、文案不清
- **P3**: 样式与体验优化
