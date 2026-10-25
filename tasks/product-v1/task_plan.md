# Direction A implementation plan

User instruction: proceed W0 through W4; mark missing real evidence BLOCKED.
Baseline: main 58a56c14c, 2026-10-25. Draft design PR #1276 is input, not a release authorization.

- W0 / #1278: reconcile documentation authority; branch docs/v1-authority-1278.
- W1 / #1277: audit real 20-session CN/US evidence using existing acceptance authority.
- W1b–W2 / #1279: four-strategy browser UAT and static/live privacy evidence.
- W3 / #1282: pinned accepted US/CN replay or exact upstream blocker.
- W4 / #1281: exercised owner runbook, release/rollback evidence and honest A0–A7 packet.

Each issue gets its own branch/PR from current main. No automatic production
release, evidence rewriting, strategy changes, new workflow or alternative state store.
Use current product docs for durable authority; retain receipts per issue.
