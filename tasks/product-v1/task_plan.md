# Direction A implementation plan

User instruction: proceed W0 through W4; mark missing real evidence BLOCKED.
Baseline: main 58a56c14c, 2026-10-25. Draft design PR #1276 is input, not a release authorization.

- W0 / #1278: authority reconciled; PR #1283 READY_FOR_REVIEW.
- W1 / #1277: real ledger delivered in #1284; A1 BLOCKED (7 observed / 0 qualified per market).
- W1b–W2 / #1279: eight live journeys and 60 fixture checks PASS; #1287 retains A3 BLOCKED / A4 FAIL, observed defect #1288.
- W3 / #1282: #1289 retains repeated accepted CN historical replay PASS and accepted US source BLOCKED.
- W4 / #1281: #1290 delivers exercised runbook, local static restore and A0–A7 NO-GO packet.
- Observed #1285 ops defect: narrow fix #1286 with 71 tests and CI PASS; actual recovery awaits reviewed merge.

Each issue gets its own branch/PR from current main. No automatic production
release, evidence rewriting, strategy changes, new workflow or alternative state store.
Use current product docs for durable authority; retain receipts per issue.
