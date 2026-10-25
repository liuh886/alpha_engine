# Observed no-change publication defect / #1285

Baseline main 58a56c14c. Real attempt 40169478271:1 failed at a legitimate
latest-main semantic-no-change result. jq -e returned 1 for boolean false before
the existing success branch. Original failed observation stays sealed.

Plan: narrowly convert a required boolean to a string before jq -e, retain
strict type checks, exercise the actual workflow expression for false/true and
invalid inputs, run existing delta/refresh and governance tests, submit for review.
No new workflow, publication route, model or evidence mutation.

Progress: implementation and workflow-bound regression added; 71 existing and
regression tests PASS, Ruff and whitespace PASS, governance 39 workflows with
zero violations. Initial command referenced a nonexistent refresh-execution test
and omitted the governance output argument; corrected to actual refresh/trigger
tests and --output/--enforce before recording results.
Actual recovery NOT_TESTED until owner-reviewed merge and a real no-change run.
