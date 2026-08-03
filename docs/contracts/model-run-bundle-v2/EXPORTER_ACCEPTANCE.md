# Generic exporter acceptance

A model workflow may publish a governed Model Run Bundle v2 only when all of the following hold:

1. The adapter declares one reviewed `model_kind` and an explicit source-input contract.
2. Required sections are present or carry a machine-readable blocker; unavailable sections never reference fabricated files.
3. Section bytes, byte counts and SHA-256 values reconcile with the manifest.
4. The four immutable identities and `bundle_id` reproduce exactly for unchanged inputs.
5. `local`, `preview` and `formal` catalogs remain isolated; preview or rejected records cannot enter the formal allow-list.
6. Existing run identities cannot be overwritten with different bytes.
7. Failed and blocked preview runs remain visible research evidence when their source contract declares them.
8. Every bundle remains `research_only=true` and `trade_ready=false`.

The reusable `.github/actions/export-model-run` action is the supported workflow entry point. New adapters must not require frontend code changes.
