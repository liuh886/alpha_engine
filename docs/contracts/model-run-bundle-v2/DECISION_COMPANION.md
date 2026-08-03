# Manifest-bound research decision companion

A completed research decision is stored outside the evidence manifest. The companion binds an immutable `bundle_id` and may cite only section paths and SHA-256 values already declared as available by that manifest.

This separation prevents a circular identity: embedding `decision.json` in the evidence manifest would change the manifest and therefore change the `bundle_id` written into the decision.

## Required behavior

- `model_decisions/catalog.json` indexes companion receipts by `run_id` and `bundle_id`.
- The receipt bytes, byte size and SHA-256 must match the catalog.
- Every gate and evidence claim must bind one available manifest section by exact path and SHA-256.
- `supported` requires a completed receipt and all gates passed.
- `not_supported` requires a completed receipt and at least one failed gate.
- `blocked` requires a blocked gate; `pending_review` must remain blocked.
- A receipt may name exactly one next permitted validation step.
- Missing receipts mean **no decision recorded**. They do not imply support, rejection or readiness.
- Invalid receipts fail closed and the frontend must display no verdict.
- Trading instructions, order language and live-position recommendations are prohibited.
- Every catalog and receipt remains `research_only=true` and `trade_ready=false`.

The browser renders the verified receipt; it does not derive a verdict from charts, metrics or narrative text.
